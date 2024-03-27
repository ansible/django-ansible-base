#  Copyright 2024 Red Hat, Inc.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import logging

from social_core.backends.github_enterprise import GithubEnterpriseTeamOAuth2

from ansible_base.authentication.authenticator_configurators.github import GithubEnterpriseTeamConfiguration
from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin
from ansible_base.authentication.social_auth import SocialAuthMixin, SocialAuthValidateCallbackMixin

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.github_enterprise_team')


class AuthenticatorPlugin(SocialAuthMixin, SocialAuthValidateCallbackMixin, GithubEnterpriseTeamOAuth2, AbstractAuthenticatorPlugin):
    configuration_class = GithubEnterpriseTeamConfiguration
    logger = logger
    type = "github-enterprise-team"
    category = "sso"
    configuration_encrypted_fields = ['SECRET']
