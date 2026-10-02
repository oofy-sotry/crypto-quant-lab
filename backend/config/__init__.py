import pymysql

# Django의 MySQL 백엔드는 mysqlclient(MySQLdb)를 기대하고 버전(>= 2.2.1)을 검사한다.
# mysqlclient는 C 확장이라 Vercel 빌드에서 설치가 어려워 순수 Python인 PyMySQL로 대체한다.
pymysql.version_info = (2, 2, 1, "final", 0)
pymysql.install_as_MySQLdb()
