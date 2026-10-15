from copy import deepcopy

from modeling.recommendation.presentation_names import display_title


def test_curated_name_is_separate_from_original_and_english():
    row = {'appid': 367520, 'name': 'Hollow Knight', 'name_en': 'Hollow Knight', 'name_zh': None}
    original = deepcopy(row)
    shown = display_title(row)
    assert shown['display_name'] == '空洞骑士'
    assert shown['display_name_en'] == 'Hollow Knight'
    assert row == original


def test_existing_chinese_name_and_english_fallback():
    assert display_title({'appid': 9991, 'name_zh': '测试游戏', 'name_en': 'Demo'})['display_name'] == '测试游戏'
    assert display_title({'appid': 9992, 'name_zh': 'Demo', 'name_en': 'Demo'})['display_name'] == 'Demo'
    assert display_title({'appid': 9993, 'name': 'Search Result'})['display_name'] == 'Search Result'


def test_nickname_is_not_used_as_primary_title():
    assert display_title({'appid': 1245620, 'name_en': 'ELDEN RING'})['display_name'] == '艾尔登法环'
    assert display_title({'appid': 2358720, 'name_en': 'Black Myth: Wukong'})['display_name'] == '黑神话：悟空'
