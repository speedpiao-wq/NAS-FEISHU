"""
配置模块：从环境变量 / .env 文件加载所有配置项。
"""
import os
from dotenv import load_dotenv

load_dotenv()


class FeishuConfig:
    """飞书开放平台配置"""
    APP_ID: str = os.getenv("FEISHU_APP_ID", "")
    APP_SECRET: str = os.getenv("FEISHU_APP_SECRET", "")
    BITABLE_APP_TOKEN: str = os.getenv("FEISHU_BITABLE_APP_TOKEN", "")
    BITABLE_TABLE_ID: str = os.getenv("FEISHU_BITABLE_TABLE_ID", "")
    VERIFICATION_TOKEN: str = os.getenv("FEISHU_VERIFICATION_TOKEN", "")
    ENCRYPT_KEY: str = os.getenv("FEISHU_ENCRYPT_KEY", "")
    API_BASE_URL: str = "https://open.feishu.cn/open-apis"


class NASConfig:
    """NAS 存储配置"""
    OUTPUT_DIR: str = os.getenv("NAS_OUTPUT_DIR", "./output/contracts")


class FlaskConfig:
    """Flask 服务配置"""
    HOST: str = os.getenv("FLASK_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("FLASK_PORT", "5000"))
    DEBUG: bool = os.getenv("FLASK_DEBUG", "false").lower() == "true"


class CompanyConfig:
    """公司信息（体现在合同头部）"""
    NAME: str = os.getenv("COMPANY_NAME", "贵公司名称")
    ADDRESS: str = os.getenv("COMPANY_ADDRESS", "公司地址")
    TEL: str = os.getenv("COMPANY_TEL", "公司电话")
    FAX: str = os.getenv("COMPANY_FAX", "公司传真")
    EMAIL: str = os.getenv("COMPANY_EMAIL", "公司邮箱")
