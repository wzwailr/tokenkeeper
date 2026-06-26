"""PostgreSQL 后端测试（需要 psycopg2）。"""

from __future__ import annotations

import unittest


class TestPostgresLedger(unittest.TestCase):
    """测试 PostgresLedger 基本功能。"""

    def test_import_without_psycopg2(self):
        """未安装 psycopg2 时，导入不应崩溃。"""
        import importlib
        try:
            import psycopg2  # noqa: F401
            HAS_PSYCOPG2 = True
        except ImportError:
            HAS_PSYCOPG2 = False

        if not HAS_PSYCOPG2:
            # 没有 psycopg2，跳过
            self.skipTest("psycopg2 未安装")

        from tokenkeeper.postgres_ledger import PostgresLedger
        self.assertTrue(callable(PostgresLedger))

    def test_requires_psycopg2(self):
        """无 psycopg2 时构造应抛 ImportError。"""
        import importlib
        try:
            import psycopg2  # noqa: F401
            self.skipTest("psycopg2 已安装，跳过此测试")
        except ImportError:
            pass

        from tokenkeeper.postgres_ledger import PostgresLedger
        with self.assertRaises(ImportError):
            PostgresLedger("postgresql://localhost/test")


if __name__ == "__main__":
    unittest.main()
