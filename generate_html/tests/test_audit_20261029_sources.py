"""Selected forecast sources survive the final dashboard source resolver."""
import json
from datetime import timedelta
from unittest import TestCase
from unittest.mock import patch

from core.model_identity import model_key
from core.models import Dashboard, SourceRef
from modules.sales_forecast import _read_actual_profiles, _small_daily_source
from tests import test_forecast_cell_sources as fixtures


class FinalForecastSourceTests(TestCase):
    def setUp(self):
        self.fixture = fixtures.ForecastCellSourceTests()
        self.addCleanup(self.fixture.doCleanups)

    def build(self, first_values, second_values, second_title=None):
        f = self.fixture
        first = f.mix('A', first_values)
        second = f.mix('B', second_values, second_title)
        store = f.store([first, second])
        aliases = {model_key(f.model): f.model}
        if second_title:
            aliases[model_key(second_title.removesuffix('by天'))] = f.model
        with patch('modules.sales_forecast._read_model_mapping', return_value=aliases), \
             patch('modules.sales_forecast.generation_records', return_value=[]):
            profiles, _ = _read_actual_profiles(store, today=f.day+timedelta(days=3))
        profile = next(p for p in profiles if p['model'] == f.model)
        board = Dashboard('sales_forecast', 'test', {'profile': profile})
        # Production resolves in the module and again in main. JSON copies
        # must also retain selected-source semantics.
        for _ in range(2):
            store.resolve_dashboard_sources(board)
            board.views = json.loads(json.dumps(board.views))
        return store, first, second, board.views['profile']

    def test_backfilled_value_points_to_second_file(self):
        _, first, second, profile = self.build([0, None], [9, 30])
        self.assertEqual([r['orders'] for r in profile['small_daily_days']], [0, 30])
        sources = profile['small_daily_sources']
        self.assertEqual(sources['2026-09-01']['file'], first.path.name)
        self.assertEqual(sources['2026-09-02']['file'], second.path.name)
        self.assertNotIn('source_files', sources['2026-09-02'])

    def test_equal_candidates_do_not_claim_unselected_source(self):
        _, first, _, profile = self.build([0, 30], [0, 30])
        for source in profile['small_daily_sources'].values():
            self.assertEqual(source['file'], first.path.name)
            self.assertNotIn('source_files', source)

    def test_backfill_keeps_physical_alias_sheet(self):
        title = 'M9旗舰2026款by天'
        _, _, second, profile = self.build([0, None], [9, 30], title)
        source = profile['small_daily_sources']['2026-09-02']
        self.assertEqual((source['file'], source['sheet']), (second.path.name, title))

    def test_merged_panel_sources_still_expand_and_sums_keep_both(self):
        store, first, second, _ = self.build([0, None], [0, 30])
        title = self.fixture.model+'by天'
        source = SourceRef(first.path.name, title)
        summed = f'{first.path.name}｜{title}、{second.path.name}｜{title}'
        board = Dashboard('test', 'test', {'source': source.to_dict(),
                          'sum_source': _small_daily_source(summed, source.to_dict())}, [source])
        store.resolve_dashboard_sources(board)
        self.assertEqual(board.views['source']['source_files'], [first.path.name, second.path.name])
        self.assertEqual(board.views['sum_source'], summed)
        self.assertEqual([(s.file, s.sheet) for s in board.sources],
                         [(first.path.name, title), (second.path.name, title)])
