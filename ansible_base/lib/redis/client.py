import copy
import logging
import os
from typing import Dict, Union
from urllib.parse import parse_qs, urlparse

from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext as _
from django_redis.client import DefaultClient
from redis import Redis
from redis.cluster import ClusterNode, RedisCluster
from redis.exceptions import RedisClusterException

from ansible_base.lib.constants import STATUS_DEGRADED, STATUS_FAILED, STATUS_GOOD

logger = logging.getLogger('ansible_base.lib.redis.client')

_DEFAULT_STATUS_TIMEOUT_SEC = 4
_REDIS_CLUSTER_OK_STATUS = 'ok'

_INVALID_STANDALONE_OPTIONS = ['cluster_error_retry_attempts']


# We are going to build our own cluster class to override the mget function
# In a redis cluster, keys might not be in the same slot and this will throw off mget.
# Instead, we are going to try and use mget and then, if we get the slot error, we will try the mget_nonatomic to make it work
class DABRedisCluster(RedisCluster):
    mode = 'cluster'

    def mget(self, *args, **kwargs):
        try:
            return super().mget(*args, **kwargs)
        except RedisClusterException as e:
            if 'MGET - all keys must map to the same key slot' in str(e):
                return super().mget_nonatomic(*args, **kwargs)
            raise


class DABRedis(Redis):
    mode = 'standalone'


class RedisClient(DefaultClient):
    """
    Get a redis_client for the django cache
    """

    def _get_client_args(self):
        return self._params.get('OPTIONS', {}).get('CLIENT_CLASS_KWARGS', {})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        connection_kwargs = self._get_client_args()
        self.mode = connection_kwargs.get('mode', 'standalone')
        self.redis_hosts = connection_kwargs.get('redis_hosts', '')

    def connect(self, index: int = 0) -> Union[DABRedis, DABRedisCluster]:
        """
        Given a connection index, returns a new raw redis client/connection
        instance. Index is used for replication setups and indicates that
        connection string should be used. In normal setups, index is 0.
        """

        # Make a deep copy of the CLIENT_CLASS_KWARGS so we don't accidentally modify the actual settings
        connection_args = copy.deepcopy(self._get_client_args())

        return get_redis_client(url=self._server[index], **connection_args)


class RedisClientGetter:
    def _redis_parse_url(self) -> None:
        if self.url == '':
            # If there is no URL we have nothing to do
            return

        # If we can't parse this just let it raise because other things will fail anyway
        parsed_url = urlparse(self.url)
        if parsed_url.scheme in ['file', 'unix']:
            # Attempt to attach to a socket if its a file or unix scheme
            self.connection_settings['unix_socket_path'] = parsed_url.path
        elif parsed_url.scheme in ['redis', 'rediss']:
            # Extract information from a rediss url
            for arg_name, parse_name in [('host', 'hostname'), ('port', 'port'), ('username', 'username'), ('password', 'password')]:
                attribute = getattr(parsed_url, parse_name, None)
                if attribute:
                    self.connection_settings[arg_name] = attribute

            if parsed_url.scheme == 'rediss' and self.connection_settings.get('ssl', None) is None:
                logger.info('Implicitly setting ssl in kwargs because URL was rediss')
                self.connection_settings['ssl'] = True

            if self.connection_settings.get('ssl') and parsed_url.scheme != 'rediss':
                self.url = self.url.replace('redis://', 'rediss://')
                logger.info("Altering redis URL to be rediss because tls was specified in kwargs")
        else:
            raise ImproperlyConfigured(_('Invalid redis URL, can only have the scheme file, unix, redis or rediss URLs, got {}').format(self.url))

        # Add the DB from the URL (if passed)
        try:
            self.connection_settings['db'] = int(parsed_url.path.split('/')[1])
        except (IndexError, ValueError):
            pass

        # Add any additional query params from the URL as kwargs
        for key, value in parse_qs(parsed_url.query).items():
            self.connection_settings[key] = value[-1]

    def _get_hosts(self) -> None:
        if not self.redis_hosts or self.redis_hosts == '':
            return

        self.connection_settings.pop('host', None)
        self.connection_settings.pop('port', None)
        self.connection_settings['startup_nodes'] = []

        translated_generic_exception = ImproperlyConfigured(_('Unable to parse redis_hosts, see logs for more details'))

        # Make sure we have a string for redis_hosts
        if not isinstance(self.redis_hosts, str):
            logger.error(f"Specified redis_hosts is not a string, got: {self.redis_hosts}")
            raise translated_generic_exception

        host_ports = self.redis_hosts.split(',')
        for host_port in host_ports:
            try:
                node, port_string = host_port.split(':')
            except ValueError:
                logger.error(f"Specified cluster_host {host_port} is not valid; it needs to be in the format <host>:<port>")
                raise translated_generic_exception

            # Make sure we have an int for the port
            try:
                port = int(port_string)
            except ValueError:
                logger.error(f'Specified port on {host_port} is not an int')
                raise translated_generic_exception

            self.connection_settings['startup_nodes'].append(ClusterNode(node, port))

    def __init__(self, *args, **kwargs):
        self.url = ''

    def get_client(self, url: str = '', **kwargs) -> Union[DABRedis, DABRedisCluster]:
        # remove our settings which are invalid to the parent classes
        self.mode = kwargs.pop('mode', 'standalone')
        self.redis_hosts = kwargs.pop('redis_hosts', None)

        self.connection_settings = kwargs
        self.url = url
        self._redis_parse_url()

        for file_setting in ['ssl_certfile', 'ssl_keyfile', 'ssl_ca_certs']:
            file = self.connection_settings.get(file_setting, None)
            if file == '':
                # Underlying libraries inspect these settings like `if ssl_ca_certs is not None`
                # However, we allow people to unset these by setting env vars as ""
                # So if we get a '' or None we are going to just remove the setting so that the underlying library does not try to validate a file named ''
                self.connection_settings.pop(file_setting)
            elif file is not None and self.connection_settings.get('ssl', None) and not os.access(file, os.R_OK):
                raise ImproperlyConfigured(_('Unable to read file {} from setting {}').format(file, file_setting))

        # Connect to either a cluster or a standalone redis
        if self.mode == 'cluster':
            logger.debug("Connecting to Redis clustered")
            self._get_hosts()
            return DABRedisCluster(**self.connection_settings)
        elif self.mode == 'standalone':
            for setting in _INVALID_STANDALONE_OPTIONS:
                if setting in self.connection_settings:
                    logger.info("Removing setting {setting} from connection settings because its invalid for standalone mode")
                    self.connection_settings.pop(setting)
            logger.debug("Connecting to Redis standalone")
            return DABRedis(**self.connection_settings)
        else:
            raise ImproperlyConfigured(_("mode must be either one of ['cluster', 'standalone'] got {}").format(self.mode))


def get_redis_client(url: str = '', **kwargs) -> Union[DABRedis, DABRedisCluster]:
    """
    Get a raw redis client based on a combination of url and kwargs
    The URL can contain things like the db and other params which will be converted into kwargs for the underlying redis client
    Or parameters for the underlying redis client can be specified directly in kwargs
    This will return a DABRedisCluster based on the kwargs "clustered" otherwise it will return a regular DABRedis client
    If clustered is specified this function also expects the setting "redis_hosts" as a string of host:port,host:port....
    """
    client_getter = RedisClientGetter()
    return client_getter.get_client(url, **kwargs)


def get_redis_status(url: str = '', timeout: int = _DEFAULT_STATUS_TIMEOUT_SEC, **kwargs) -> Dict:
    for setting in ['socket_timeout', 'socket_connect_timeout']:
        if setting not in kwargs:
            kwargs[setting] = timeout
    if 'socket_keepalive' not in kwargs:
        kwargs['socket_keepalive'] = True

    kwargs.pop('retry', None)

    response = {
        'mode': 'Unknown',
        'status': 'Unknown',
    }

    try:
        redis_client = get_redis_client(url, **kwargs)
        response['mode'] = redis_client.mode
        response['status'] = STATUS_GOOD
        if redis_client.mode == 'standalone':
            response['ping'] = redis_client.execute_command('PING')
        elif redis_client.mode == 'cluster':
            response['cluster_info'] = redis_client.cluster_info()
            response['cluster_nodes'] = redis_client.cluster_nodes()
            response['status'] = determine_cluster_node_status(response['cluster_nodes'])
            # Now our status should be STATUS_GOOD or STATUS_DEGRADED
            # There is one more check we need to do and that is if the cluster_info did not return ok we are in a bad state
            if response['cluster_info']['cluster_state'] != _REDIS_CLUSTER_OK_STATUS:
                response['status'] = STATUS_FAILED
    except Exception as e:
        response['status'] = STATUS_FAILED
        response['exception'] = str(e)
        logger.exception("Failed getting redis status")

    return response


def determine_cluster_node_status(cluster_nodes: Dict) -> str:
    # A general marker that there is at least 1 failed node in the cluster
    has_bad_node = False
    for response_node in cluster_nodes.values():
        if 'fail' in response_node['flags']:
            has_bad_node = True

    if has_bad_node:
        return STATUS_DEGRADED

    return STATUS_GOOD
