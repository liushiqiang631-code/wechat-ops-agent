from __future__ import annotations

from app.config.settings import Settings


def test_dangerous_actions_are_disabled_by_default():
    settings = Settings(_env_file=None)

    assert settings.wechat_draft_enabled is False
    assert settings.auto_publish is False
    assert settings.enable_intentional_typos is False
    assert settings.image_model_enabled is False


def test_secret_values_are_not_in_repr_or_serialized_output():
    settings = Settings(
        _env_file=None,
        deepseek_api_key="model-secret",
        wechat_app_secret="wechat-secret",
        siliconflow_api_key="sf-secret",
        dashscope_api_key="dashscope-secret",
    )

    rendered = repr(settings)
    dumped = settings.public_dict()

    assert "model-secret" not in rendered
    assert "wechat-secret" not in rendered
    assert "sf-secret" not in rendered
    assert "dashscope-secret" not in rendered
    assert "deepseek_api_key" not in dumped
    assert "wechat_app_secret" not in dumped
    assert "siliconflow_api_key" not in dumped
    assert "dashscope_api_key" not in dumped


def test_deepseek_v4_pro_is_the_default_brain():
    settings = Settings(_env_file=None)

    assert settings.text_model_provider == "deepseek"
    assert settings.deepseek_model == "deepseek-v4-pro"
    assert settings.deepseek_api_base == "https://api.deepseek.com"


def test_operator_name_is_configurable_and_published_without_secrets():
    settings = Settings(_env_file=None, operator_name="测试运营者")
    dumped = settings.public_dict()

    assert settings.operator_name == "测试运营者"
    assert dumped["operator_name"] == "测试运营者"
    assert "search_api_key" not in dumped
