import copy
from unittest import mock

import pytest
from django.core.exceptions import ImproperlyConfigured
from django_redis.cache import RedisCache
from redis.client import Redis
from redis.cluster import ClusterNode
from redis.exceptions import RedisClusterException

from ansible_base.lib.redis.client import DABRedisCluster, RedisClient, RedisClientGetter, get_redis_client


@pytest.mark.parametrize(
    "mode,redis_hosts, args",
    [
        (
            'standalone',
            'localhost',
            {},
        ),
        ('standalone', 'localhost', {'OPTIONS': {}}),
        ('standalone', 'localhost', {'OPTIONS': {'CLIENT_CLASS_KWARGS': {}}}),
        # Items in the CLIENT_CLASS_KWARGS are overwritten by the URL
        ('standalone', 'localhost', {'OPTIONS': {'CLIENT_CLASS_KWARGS': {'host': 'b'}}}),
        ('standalone', 'localhost', {'OPTIONS': {'CLIENT_CLASS_KWARGS': {'mode': 'standalone'}}}),
        ('cluster', 'a', {'OPTIONS': {'CLIENT_CLASS_KWARGS': {'mode': 'cluster', 'redis_hosts': 'a:1'}}}),
        ('standalone', 'localhost', {'OPTIONS': {'CLIENT_CLASS_KWARGS': {'redis_hosts': ''}}}),
        ('standalone', 'localhost', {'OPTIONS': {'CLIENT_CLASS_KWARGS': {'redis_hosts': 'a:1'}}}),
    ],
)
def test_redis_client_init(args, mode, redis_hosts):
    redis_cache = RedisCache('redis://localhost', args)
    client = RedisClient('redis://localhost', args, redis_cache)
    with mock.patch('redis.cluster.RedisCluster.__init__', return_value=None) as rcm:
        with mock.patch('redis.Redis.__init__', return_value=None) as rm:
            client.connect()
            if mode == 'cluster':
                rm.assert_not_called
                rcm.assert_called_once
                assert 'startup_nodes' in rcm.call_args.kwargs
                assert rcm.call_args.kwargs['startup_nodes'] == [ClusterNode('a', '1')]
            else:
                rcm.assert_not_called
                rm.assert_called_once
                assert 'host' in rm.call_args.kwargs
                assert rm.call_args.kwargs['host'] == redis_hosts


def test_cluster_with_no_hosts():
    """
    You can't build a cluster without cluster_hosts
    """
    with pytest.raises(RedisClusterException):
        get_redis_client(url="file://localhost", **{'mode': 'cluster'})


def test_redis_client_confirm_connect_does_not_change_options():
    args = {'OPTIONS': {'CLIENT_CLASS_KWARGS': {'mode': 'standalone', 'redis_hosts': 'a:1'}}}
    validate_args = copy.deepcopy(args)
    redis_cache = RedisCache('file://localhost', args)
    client = RedisClient('redis://localhost', args, redis_cache)
    client.connect()
    assert args == validate_args


@pytest.mark.parametrize(
    "url,host,port,username,password,db,raises,socket",
    [
        ('localhost', 'localhost', 6379, None, None, 0, True, None),
        ('redis://my_mom:her_pass@example.com:1234/1', 'example.com', 1234, 'my_mom', 'her_pass', 1, False, None),  # NOSONAR
        ('redis://my_mom:her_pass@example.com/1', 'example.com', 6379, 'my_mom', 'her_pass', 1, False, None),  # NOSONAR
        ('redis://my_mom@example.com/', 'example.com', 6379, 'my_mom', None, 0, False, None),
        ('redis://:her_pass@example.com/', 'example.com', 6379, None, 'her_pass', 0, False, None),
        ('redis://example.com:1234/a', 'example.com', 1234, None, None, 0, False, None),
        ('unix:///var/temp/my.socket', None, None, None, None, 0, False, '/var/temp/my.socket'),
        ('unix:///var/temp/my.socket?db=junk', None, None, None, None, 'junk', False, '/var/temp/my.socket'),
        ('file:///var/temp/my.socket?db=junk', None, None, None, None, 'junk', False, '/var/temp/my.socket'),
        ('file:///var/temp/my.socket?port=junk', None, None, None, None, 0, False, '/var/temp/my.socket'),  # A socket will prevent a port from being set
        ('file:///var/temp/my.socket?password=junk', None, None, None, 'junk', 0, False, '/var/temp/my.socket'),
    ],
)
def test_redis_client_location_parsing(url, host, port, username, password, db, raises, socket):
    args = {'OPTIONS': {'CLIENT_CLASS_KWARGS': {'mode': 'standalone'}}}
    redis_cache = RedisCache(url, args)
    client = RedisClient(url, args, redis_cache)
    connection = None
    try:
        connection = client.connect()
    except ImproperlyConfigured as ic:
        if not raises:
            raise ic
    if connection:
        assert connection.connection_pool.connection_kwargs.get('host', None) == host
        assert connection.connection_pool.connection_kwargs.get('port', None) == port
        assert connection.connection_pool.connection_kwargs.get('username', None) == username
        assert connection.connection_pool.connection_kwargs.get('password', None) == password
        assert connection.connection_pool.connection_kwargs.get('db', None) == db
        # The unix_socket_path gets converted to path in the connection_pool
        assert connection.connection_pool.connection_kwargs.get('path', None) == socket


@pytest.mark.parametrize("mode,expect_exception", [('cluster', True), ('standalone', False)])
def test_redis_client_right_connection_type(mode, expect_exception):
    args = {'OPTIONS': {'CLIENT_CLASS_KWARGS': {'mode': mode, 'redis_hosts': 'a:1'}}}
    redis_cache = RedisCache('localhost', args)
    client = RedisClient('redis://localhost', args, redis_cache)

    # When creating a cluster the cluster initialization tries to connect to the cluster.
    # Since we don't have one running we expect a redis.exceptions.RedisClusterException to be raised
    if expect_exception:
        with pytest.raises(RedisClusterException):
            connection = client.connect()
    else:
        connection = client.connect()
        assert isinstance(connection, Redis)


def test_redis_client_cluster_of_redis_hosts():
    args = {'OPTIONS': {'CLIENT_CLASS_KWARGS': {'mode': 'cluster', 'redis_hosts': 'a:1'}}}
    redis_cache = RedisCache('localhost', args)
    client = RedisClient('redis://localhost', args, redis_cache)
    with mock.patch('redis.cluster.RedisCluster.__init__', return_value=None) as m:
        client.connect()
        assert 'host' not in m.call_args.kwargs
        assert 'port' not in m.call_args.kwargs
        assert 'startup_nodes' in m.call_args.kwargs
        assert len(m.call_args.kwargs['startup_nodes']) == 1


def test_redis_client_cluster_from_url():
    args = {'OPTIONS': {'CLIENT_CLASS_KWARGS': {'mode': 'cluster', 'redis_hosts': ''}}}
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
    "redis_hosts,raises,expected_length",
    [
        (True, True, None),
        (1, True, None),
        ('a:1', False, 1),
        ('a:1,b:1', False, 2),
        ('a:b', True, None),
        ('a,b,c', True, None),
    ],
)
def test_redis_client_cluster_hosts_parsing(redis_hosts, raises, expected_length):
    args = {'OPTIONS': {'CLIENT_CLASS_KWARGS': {'mode': 'cluster', 'redis_hosts': redis_hosts}}}
    redis_cache = RedisCache('redis://localhost', args)
    client = RedisClient('redis://localhost', args, redis_cache)
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
    redis_cache = RedisCache('redis://localhost', args)
    client = RedisClient('redis://localhost', args, redis_cache)
    with pytest.raises(ImproperlyConfigured) as ic:
        client.connect()
        assert 'Unable to read file' in ic


def test_redis_client_read_files_no_tls():
    args = {'OPTIONS': {'CLIENT_CLASS_KWARGS': {'mode': 'standalone', 'ssl_certfile': '/tmp/junk.does.not.exist'}}}
    redis_cache = RedisCache('redis://localhost', args)
    client = RedisClient('redis://localhost', args, redis_cache)
    client.connect()


def test_redis_client_ssl_settings_empty_strings():
    args = {'OPTIONS': {'CLIENT_CLASS_KWARGS': {'mode': 'standalone', 'ssl_certfile': '', 'some_other_setting': 4}}}
    redis_cache = RedisCache('redis://localhost', args)
    client = RedisClient('redis://localhost', args, redis_cache)
    with mock.patch('redis.Redis.__init__', return_value=None) as m:
        client.connect()
        assert 'ssl_certfile' not in m.cal_args.kwargs
        assert 'some_other_setting' in m.call_args.kwargs


def test_redis_tls_is_set_based_on_rediss_url():
    args = {'OPTIONS': {'CLIENT_CLASS_KWARGS': {'mode': 'standalone'}}}
    redis_cache = RedisCache('rediss://localhost', args)
    client = RedisClient('rediss://localhost', args, redis_cache)
    with mock.patch('redis.Redis.__init__', return_value=None) as m:
        client.connect()
        assert 'ssl' not in m.cal_args.kwargs
        assert m.call_args.kwargs['ssl'] is True


def test_get_redis_client_without_url():
    with pytest.raises(RedisClusterException) as e:
        get_redis_client(**{'mode': 'cluster', 'redis_hosts': 'localhost:6370'})
        assert 'Redis Cluster cannot be connected' in e


def test_parse_url_short_circuit():
    with mock.patch('ansible_base.lib.redis.client.urlparse') as m:
        client_getter = RedisClientGetter()
        client_getter._redis_parse_url()
        m.assert_not_called()
