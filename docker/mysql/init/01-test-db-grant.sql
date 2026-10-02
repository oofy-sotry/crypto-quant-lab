-- Django 테스트 러너가 test_<DB명> 데이터베이스를 만들고 지울 수 있도록 권한을 준다.
GRANT ALL PRIVILEGES ON `test_cryptoquant`.* TO 'cryptoquant'@'%';
