"""应用配置加载测试（F1.3）。

验证 ``app.core.config.settings`` 的实例化、关键配置项默认值
以及 LLM 相关配置项是否存在。
"""

from app.core.config import Settings, get_settings, settings


class TestSettings:
    """Settings 配置加载测试。"""

    def test_settings_instance_exists(self):
        """settings 模块级单例应存在且为 Settings 实例。"""
        assert settings is not None
        assert isinstance(settings, Settings)

    def test_get_settings_returns_singleton(self):
        """get_settings 应返回缓存的同一实例（lru_cache）。"""
        first = get_settings()
        second = get_settings()
        assert first is second
        assert isinstance(first, Settings)

    def test_database_url_has_default(self):
        """DATABASE_URL 应有非空默认值且使用 asyncpg 驱动。"""
        assert settings.DATABASE_URL
        assert "asyncpg" in settings.DATABASE_URL

    def test_secret_key_has_default(self):
        """SECRET_KEY 应有非空默认值，供 JWT 签名使用。"""
        assert settings.SECRET_KEY
        assert isinstance(settings.SECRET_KEY, str)
        # 默认密钥长度应满足 HS256 最低要求
        assert len(settings.SECRET_KEY) >= 16

    def test_jwt_algorithm_default(self):
        """ALGORITHM 默认应为 HS256。"""
        assert settings.ALGORITHM == "HS256"

    def test_access_token_expire_default(self):
        """ACCESS_TOKEN_EXPIRE_MINUTES 应为正整数。"""
        assert isinstance(settings.ACCESS_TOKEN_EXPIRE_MINUTES, int)
        assert settings.ACCESS_TOKEN_EXPIRE_MINUTES > 0

    def test_llm_model_path_config_exists(self):
        """LLM_MODEL_PATH 配置项应存在且为非空字符串。"""
        assert hasattr(settings, "LLM_MODEL_PATH")
        assert settings.LLM_MODEL_PATH
        assert isinstance(settings.LLM_MODEL_PATH, str)

    def test_embedding_model_path_config_exists(self):
        """EMBEDDING_MODEL_PATH 配置项应存在。"""
        assert hasattr(settings, "EMBEDDING_MODEL_PATH")
        assert settings.EMBEDDING_MODEL_PATH

    def test_allowed_extensions_list_property(self):
        """allowed_extensions_list 属性应返回列表，包含 .pdf 等扩展名。"""
        exts = settings.allowed_extensions_list
        assert isinstance(exts, list)
        assert len(exts) > 0
        assert ".pdf" in exts

    def test_max_file_size_positive(self):
        """MAX_FILE_SIZE 应为正整数。"""
        assert isinstance(settings.MAX_FILE_SIZE, int)
        assert settings.MAX_FILE_SIZE > 0

    def test_app_name_default(self):
        """APP_NAME 默认应为 Hansight。"""
        assert settings.APP_NAME == "Hansight"
