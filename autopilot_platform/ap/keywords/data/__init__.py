"""数据类关键字（Database/Redis/SSH/FTP）。导入子模块触发注册。

redis/paramiko 为可选依赖（懒加载）；DB 默认 sqlite(stdlib)，FTP 用 ftplib(stdlib)。
"""

from . import database              # noqa: F401  DatabaseKeyword（基础 + Hive/校验扩展）
from . import redis_keywords        # noqa: F401  RedisKeyword（基础 + hash/set/zset/list/ttl…）
from . import ssh                   # noqa: F401  SshKeyword（命令 + sftp 上传/下载）
from . import ftp                   # noqa: F401
from . import kafka_keywords        # noqa: F401  Kafka（kafka-python 懒加载）
from . import elasticsearch_keywords  # noqa: F401  ElasticSearch（elasticsearch 懒加载）
from . import hbase_keywords        # noqa: F401  HBase（happybase 懒加载）

__all__ = ["database", "redis_keywords", "ssh", "ftp",
           "kafka_keywords", "elasticsearch_keywords", "hbase_keywords"]
