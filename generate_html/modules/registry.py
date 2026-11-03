from modules.cancellation import CancellationModule
from modules.channel_analysis import ChannelAnalysisModule
from modules.conversion import ConversionModule
from modules.generic import GenericModule
from modules.launch_rhythm import LaunchRhythmModule
from modules.option_fee import OptionFeeModule
from modules.order_mix import LockMixModule, OrderMixModule, SmallOrderMixModule
from modules.overview import OverviewModule
from modules.sku import SkuModule


MODULES = [
    OverviewModule(),
    ChannelAnalysisModule(),
    LaunchRhythmModule(),
    CancellationModule(),
    ConversionModule(),
    OrderMixModule(),
    LockMixModule(),
    SmallOrderMixModule(),
    OptionFeeModule(),
    SkuModule(),
    GenericModule(),
]
