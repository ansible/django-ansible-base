import copy
from unittest import mock

import pytest
from django.core.exceptions import ImproperlyConfigured
from django_redis.cache import RedisCache
from redis.client import Redis
from redis.exceptions import RedisClusterException

from ansible_base.lib.redis.client import DABRedisCluster, RedisClient


@pytest.mark.parametrize(
    "args,clustered,clustered_hosts",
    [
        ({}, False, ''),
        ({'OPTIONS': {}}, False, ''),
        ({'OPTIONS': {'CLIENT_CLASS_KWARGS': {}}}, False, ''),
        ({'OPTIONS': {'CLIENT_CLASS_KWARGS': {'clustered': False}}}, False, ''),
        ({'OPTIONS': {'CLIENT_CLASS_KWARGS': {'clustered': True}}}, True, ''),
        ({'OPTIONS': {'CLIENT_CLASS_KWARGS': {'clustered_hosts': ''}}}, False, ''),
        ({'OPTIONS': {'CLIENT_CLASS_KWARGS': {'clustered_hosts': 'a:1'}}}, False, 'a:1'),
    ],
)
def test_redis_client_init(args, clustered, clustered_hosts):
    redis_cache = RedisCache('localhost', args)
    client = RedisClient('localhost', args, redis_cache)
    assert client.clustered is clustered
    assert client.clustered_hosts == clustered_hosts


def test_redis_client_confirm_connect_does_not_change_options():
    args = {'OPTIONS': {'CLIENT_CLASS_KWARGS': {'clustered': False, 'clustered_hosts': 'a:1'}}}
    validate_args = copy.deepcopy(args)
    redis_cache = RedisCache('localhost', args)
    client = RedisClient('localhost', args, redis_cache)
    client.connect()
    assert args == validate_args


@pytest.mark.parametrize(
    "url,host,port,username,password,db",
    [
        ('localhost', 'localhost', 6379, None, None, 0),
        ('redis://my_mom:her_pass@example.com:1234/1', 'example.com', 1234, 'my_mom', 'her_pass', 1),  # NOSONAR
        ('redis://my_mom:her_pass@example.com/1', 'example.com', 6379, 'my_mom', 'her_pass', 1),  # NOSONAR
        ('redis://my_mom@example.com/', 'example.com', 6379, 'my_mom', None, 0),
        ('redis://:her_pass@example.com/', 'example.com', 6379, None, 'her_pass', 0),
        ('redis://example.com:1234/a', 'example.com', 1234, None, None, 0),
    ],
)
def test_redis_client_url_parsing(url, host, port, username, password, db):
    redis_cache = RedisCache(url, {})
    client = RedisClient(url, {}, redis_cache)
    connection = client.connect()
    assert connection.connection_pool.connection_kwargs.get('host', None) == host
    assert connection.connection_pool.connection_kwargs.get('port', None) == port
    assert connection.connection_pool.connection_kwargs.get('username', None) == username
    assert connection.connection_pool.connection_kwargs.get('password', None) == password
    assert connection.connection_pool.connection_kwargs.get('db', None) == db


@pytest.mark.parametrize("clustered,expect_exception", [(True, True), (False, False)])
def test_redis_client_right_connection_type(clustered, expect_exception):
    args = {'OPTIONS': {'CLIENT_CLASS_KWARGS': {'clustered': clustered, 'clustered_hosts': 'a:1'}}}
    redis_cache = RedisCache('localhost', args)
    client = RedisClient('localhost', args, redis_cache)

    # When creating a cluster the cluster initialization tries to connect to the cluster.
    # Since we don't have one running we expect a redis.exceptions.RedisClusterException to be raised
    if expect_exception:
        with pytest.raises(RedisClusterException):
            connection = client.connect()
    else:
        connection = client.connect()
        assert isinstance(connection, Redis)


def test_redis_client_cluster_of_clustered_hosts():
    args = {'OPTIONS': {'CLIENT_CLASS_KWARGS': {'clustered': True, 'clustered_hosts': 'a:1'}}}
    redis_cache = RedisCache('localhost', args)
    client = RedisClient('localhost', args, redis_cache)
    with mock.patch('redis.cluster.RedisCluster.__init__', return_value=None) as m:
        client.connect()
        assert 'host' not in m.call_args.kwargs
        assert 'port' not in m.call_args.kwargs
        assert 'startup_nodes' in m.call_args.kwargs
        assert len(m.call_args.kwargs['startup_nodes']) == 1


def test_redis_client_cluster_from_url():
    args = {'OPTIONS': {'CLIENT_CLASS_KWARGS': {'clustered': True, 'clustered_hosts': ''}}}
    redis_cache = RedisCache('redis://example.com:1234', args)
    client = RedisClient('redis://example.com:1234', args, redis_cache)
    with mock.patch('redis.cluster.RedisCluster.__init__', return_value=None) as m:
        client.connect()
        assert 'host' in m.call_args.kwargs and m.call_args.kwargs['host'] == 'example.com'
        assert 'port' in m.call_args.kwargs and m.call_args.kwargs['port'] == 1234
        assert 'startup_nodes' not in m.call_args.kwargs


def test_redis_cluster_mget_success():
    # We have to mock init because the redis cluster will attempt to connect by default
    with mock.patch('redis.cluster.RedisCluster.__init__', return_value=None):
        with mock.patch('ansible_base.lib.redis.client.RedisCluster.mget') as mget_mock:
            with mock.patch('ansible_base.lib.redis.client.RedisCluster.mget_nonatomic') as mget_nonatomic_mock:
                cluster = DABRedisCluster()
                cluster.mget('a')
                assert mget_mock.assert_called
                assert mget_nonatomic_mock.assert_not_called


def test_redis_cluster_mget_raises_random_exception():
    # We have to mock init because the redis cluster will attempt to connect by default
    with mock.patch('redis.cluster.RedisCluster.__init__', return_value=None):
        with mock.patch('ansible_base.lib.redis.client.RedisCluster.mget', side_effect=Exception('This is not the exception you are looking for')) as mget_mock:
            with mock.patch('ansible_base.lib.redis.client.RedisCluster.mget_nonatomic') as mget_nonatomic_mock:
                cluster = DABRedisCluster()
                with pytest.raises(Exception):
                    cluster.mget('a')
                    assert mget_mock.assert_called
                    assert mget_nonatomic_mock.assert_not_called


def test_redis_cluster_mget_raises_expected_exception_with_wrong_message():
    # We have to mock init because the redis cluster will attempt to connect by default
    with mock.patch('redis.cluster.RedisCluster.__init__', return_value=None):
        with mock.patch(
            'ansible_base.lib.redis.client.RedisCluster.mget', side_effect=RedisClusterException('This is not the exception you are looking for')
        ) as mget_mock:
            with mock.patch('ansible_base.lib.redis.client.RedisCluster.mget_nonatomic') as mget_nonatomic_mock:
                cluster = DABRedisCluster()
                with pytest.raises(Exception):
                    cluster.mget('a')
                    assert mget_mock.assert_called
                    assert mget_nonatomic_mock.assert_not_called


def test_redis_cluster_mget_raises_expected_exception():
    # We have to mock init because the redis cluster will attempt to connect by default
    with mock.patch('redis.cluster.RedisCluster.__init__', return_value=None):
        with mock.patch(
            'ansible_base.lib.redis.client.RedisCluster.mget', side_effect=RedisClusterException('MGET - all keys must map to the same key slot')
        ) as mget_mock:
            with mock.patch('ansible_base.lib.redis.client.RedisCluster.mget_nonatomic') as mget_nonatomic_mock:
                cluster = DABRedisCluster()
                cluster.mget('a')
                assert mget_mock.assert_called
                assert mget_nonatomic_mock.assert_called


@pytest.mark.parametrize(
    "clustered_hosts,raises,expected_length",
    [
        (True, True, None),
        (1, True, None),
        ('a:1', False, 1),
        ('a:1,b:1', False, 2),
        ('a:b', True, None),
        ('a,b,c', True, None),
    ],
)
def test_redis_client_cluster_hosts_parsing(clustered_hosts, raises, expected_length):
    args = {'OPTIONS': {'CLIENT_CLASS_KWARGS': {'clustered': True, 'clustered_hosts': clustered_hosts}}}
    redis_cache = RedisCache('localhost', args)
    client = RedisClient('localhost', args, redis_cache)
    with mock.patch('redis.cluster.RedisCluster.__init__', return_value=None) as m:
        if raises:
            with pytest.raises(ImproperlyConfigured):
                client.connect()
        else:
            client.connect()
            assert 'host' not in m.call_args.kwargs
            assert 'port' not in m.call_args.kwargs
            assert 'startup_nodes' in m.call_args.kwargs
            assert len(m.call_args.kwargs['startup_nodes']) == expected_length


def test_redis_client_read_files():
    args = {'OPTIONS': {'CLIENT_CLASS_KWARGS': {'ssl_certfile': '/tmp/junk.does.not.exist', 'ssl': True}}}
    redis_cache = RedisCache('localhost', args)
    client = RedisClient('localhost', args, redis_cache)
    with pytest.raises(ImproperlyConfigured) as ic:
        client.connect()
        assert 'Unable to read file' in ic


def test_redis_client_read_files_no_tls():
    args = {'OPTIONS': {'CLIENT_CLASS_KWARGS': {'ssl_certfile': '/tmp/junk.does.not.exist'}}}
    redis_cache = RedisCache('localhost', args)
    client = RedisClient('localhost', args, redis_cache)
    client.connect()
