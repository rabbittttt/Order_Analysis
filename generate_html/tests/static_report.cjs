const path = require('node:path');

// A build under test can live outside the project's output directory.
module.exports = function staticReport(explicitPath) {
  const supplied = explicitPath || process.env.ORDER_TEST_HTML;
  return supplied ? path.resolve(supplied) :
    path.resolve(__dirname, '../../../output_file/鸿蒙智行订单分析汇总_静态版.html');
};
