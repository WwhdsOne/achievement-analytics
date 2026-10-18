"""分析参数复制自WWH；默认highest复现其已发布三图，原代码当前参数为start。

仅分析已存模型结果，不包含采集、分类或API参数。
"""

STORY_CONF_MIN = 0.6
ALLOW_MULTI_ENDING = True
CURVE_BASELINE = 'highest'
REQUIRE_START_CHAIN = False
MIN_COMMON_CHECKPOINTS = 2
RAWG_MIN_DENOMINATOR = 20
RAWG_THRESHOLDS = (10, 20, 50)
RAWG_FOUR_STATUS = True
BOOTSTRAP_SAMPLES = 2000
RANDOM_STATE = 42


def snapshot() -> dict[str, object]:
    """Capture all effective analysis parameters for reproducibility."""
    return {name: globals()[name] for name in ('STORY_CONF_MIN', 'ALLOW_MULTI_ENDING', 'CURVE_BASELINE', 'REQUIRE_START_CHAIN', 'MIN_COMMON_CHECKPOINTS', 'RAWG_MIN_DENOMINATOR', 'RAWG_THRESHOLDS', 'RAWG_FOUR_STATUS', 'BOOTSTRAP_SAMPLES', 'RANDOM_STATE')}
