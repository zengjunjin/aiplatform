from app.models.factory import ModelRegistry


def init_model_registry() -> None:
    '''在应用启动时初始化 ModelRegistry，从 LLM_PROVIDERS 配置加载所有 Provider'''
    ModelRegistry.init_from_config()