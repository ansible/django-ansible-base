# OAuth2 Provider

django-ansible-base has can serve as an OAuth2 provider similar to how AWX can.

OAuth2 is a means of doing token-based authentication. With this application install, users will be able to manage OAuth2 tokens as well as applications, a server-side representation of API clients used to generate tokens. With OAuth2, a user can authenticate by passing a token as part of the HTTP authentication header. The token can be scoped to have more restrictive permissions on top of the base RBAC permissions of the user used when creating the token.  Refer to [RFC 6749](https://tools.ietf.org/html/rfc6749) for more details of OAuth2 specification.

## Installation

Add `ansible_base.oauth2_provider` to your installed apps:

```
INSTALLED_APPS = [
    ...
    'ansible_base.oauth2_provider',
]
```
### URLs

This feature includes URLs which you will get if you are using [dynamic urls](../Installation.md).

If you want to manually add the URLs without dynamic urls, see the `oauth2_provider/urls.py` file. You will need to add variables at multiple locations within your apps API.

### Additional Settings
Additional settings are required to enable OAuth2 for your rest endpoints.
This will happen automatically if using [dynamic_settings](../Installation.md)

To manually configure the settings in your application 
```
OAUTH2_PROVIDER = {
    'ACCESS_TOKEN_EXPIRE_SECONDS': 31536000000
    'AUTHORIZATION_CODE_EXPIRE_SECONDS': 600
    'REFRESH_TOKEN_EXPIRE_SECONDS': 2628000
    'APPLICATION_MODEL': 'dab_oauth2_provider.OAuth2Application'
    'ACCESS_TOKEN_MODEL': 'dab_oauth2_provider.OAuth2AccessToken'
}

REST_FRAMEWORK = [
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'ansible_base.oauth2_provider.authentication.LoggedOAuth2Authentication',
        ...
    ]
]
OAUTH2_PROVIDER_APPLICATION_MODEL = 'dab_oauth2_provider.OAuth2Application'
OAUTH2_PROVIDER_ACCESS_TOKEN_MODEL = 'dab_oauth2_provider.OAuth2AccessToken'
OAUTH2_PROVIDER_REFRESH_TOKEN_MODEL = "dab_oauth2_provider.OAuth2RefreshToken"
OAUTH2_PROVIDER_ID_TOKEN_MODEL = "dab_oauth2_provider.OAuth2IDToken"

ALLOW_OAUTH2_FOR_EXTERNAL_USERS = False
```

### Runtime settings
You may want to allow for some of the settings above to be runtime instead of hard coded. These might include the EXPIRE_SECONDS and ALLOW_OATUH2_FOR_EXTERNAL_USERS.


### Application considerations
Note: you application must use Organizations. see [Orgnizations](../lib/organiations.md)


## Differences from AWX

* Because of how DAB's router works, we don't allow for POSTing to (for example)
  `/applications/PK/tokens/` to create a token which belongs to an application.
  The workaround is to just use /tokens/ and in the body specify
  `{"application": PK}`.
* AWX uses an older pinned version of django-oauth-toolkit whereas dab uses the current version.

## Basic Usage

To get started using OAuth2 tokens for accessing the browsable API using OAuth2, this document will walk through the steps of acquiring a token and using it.  

1. Make an application with `authorization_grant_type` set to 'password'. HTTP POST the following to the `/applications/`  endpoint (supplying your own `organization-id`):
```
{
    "name": "Admin Internal Application",
    "description": "For use by secure services & clients. ",
    "client_type": "confidential",
    "redirect_uris": "",
    "authorization_grant_type": "password",
    "skip_authorization": false,
    "organization": <organization-id>
}
```
2. Make a token with a POST to the `/tokens/` endpoint:
```
{
    "description": "My Access Token",
    "application": <application-id>,
    "scope": "write"
}
```
This will return a `<token-value>` that you can use to authenticate with for future requests (this will not be shown again)

3. Use the token to access a resource.  We will use `curl` to demonstrate this:
```
curl -H "Authorization: Bearer <token-value>" -X GET https://<server>/api/users/
```
> The `-k` flag may be needed if you have not set up a CA yet and are using SSL.  

This token can be revoked by making a DELETE on the detail page for that token.  All you need is that token's id.  For example:
```
curl -ku <user>:<password> -X DELETE https://<service>/api/tokens/<pk>/
```

Similarly, using a token:
```
curl -H "Authorization: Bearer <token-value>" -X DELETE https://<service>/api/tokens/<pk>/ -k
```


## More Information

#### Managing OAuth2 Applications and Tokens

Applications and tokens can be managed as a top-level resource at `/api/applications` and
`/api/tokens`. These resources can also be accessed respective to the user at
`/api/users/N/<resource>`.  Applications can be created by making a POST to either `api/applications`
or `/api/users/N/applications`.  

Each OAuth2 application represents a specific API client on the server side. For an API client to use the API via an application token,
it must first have an application and issue an access token.  

Individual applications will be accessible via their primary keys:
`/api/applications/<pk>/`. Here is a typical application:
```
        {
            "id": 1,
            "url": "/api/gateway/v1/applications/1/",
            "related": {
                "access_tokens": "/api/gateway/v1/applications/1/tokens/",
                "activity_stream": "/api/gateway/v1/activitystream/?content_type=31&object_id=1",
                "created_by": "/api/gateway/v1/users/2/",
                "modified_by": "/api/gateway/v1/users/2/",
                "organization": "/api/gateway/v1/organizations/1/",
                "user": "/api/gateway/v1/users/2/"
            },
            "summary_fields": {
                "modified_by": {
                    "id": 2,
                    "username": "admin",
                    "first_name": "",
                    "last_name": ""
                },
                "created_by": {
                    "id": 2,
                    "username": "admin",
                    "first_name": "",
                    "last_name": ""
                },
                "user": {
                    "id": 2,
                    "username": "admin",
                    "first_name": "",
                    "last_name": ""
                },
                "organization": {
                    "id": 1,
                    "name": "Test Org"
                },
                "tokens": {
                    "count": 1,
                    "results": [
                        {
                            "id": 1,
                            "token": "$encrypted$",
                            "scope": "write"
                        }
                    ]
                }
            },
            "created": "2024-05-09T18:55:19.590952Z",
            "created_by": 2,
            "modified": "2024-05-09T18:55:19.590912Z",
            "modified_by": 2,
            "name": "My Test Application",
            "client_id": "KwhtxfwpG19J4H6wKenregyzjdrH7hRwMV578Zmj",
            "redirect_uris": "",
            "post_logout_redirect_uris": "",
            "client_secret": "$encrypted$",
            "algorithm": "",
            "user": 2,
            "description": "",
            "logo_data": "",
            "organization": 1,
            "client_type": "confidential",
            "skip_authorization": false,
            "authorization_grant_type": "password"
        }
```
In the above example, `user` is the primary key of the user associated to this application and `name` is
 a human-readable identifier for the application. The other fields, like `client_id` and
`redirect_uris`, are mainly used for OAuth2 authorization, which will be covered later in the 'Using
OAuth2 Token System' section.

Fields `client_id` and `client_secret` are immutable identifiers of applications, and will be
generated during creation; Fields `user` and `authorization_grant_type`, on the other hand, are
*immutable on update*, meaning they are required fields on creation, but will become read-only after
that.

**On RBAC side:**
- System admins will be able to see and manipulate all applications in the system;
- Organization admins will be able to see and manipulate all applications belonging to Organization
  members;
- Other normal users will only be able to see, update and delete their own applications, but
  cannot create any new applications.

Tokens, on the other hand, are resources used to actually authenticate incoming requests and mask the
permissions of the underlying user. Tokens can be created by POSTing to `/api/tokens/`
endpoint by providing `application` and `scope` fields to point to related application and specify
token scope; or POSTing to `/api/applications/<pk>/tokens/` by providing only `scope`, while
the parent application will be automatically linked.

Individual tokens will be accessible via their primary keys at
`/api/tokens/<pk>/`. Here is a typical token:
```
        {
            "id": 1,
            "url": "/api/gateway/v1/tokens/1/",
            "related": {
                "activity_stream": "/api/gateway/v1/activitystream/?content_type=34&object_id=1",
                "application": "/api/gateway/v1/applications/1/",
                "created_by": "/api/gateway/v1/users/2/",
                "modified_by": "/api/gateway/v1/users/2/",
                "user": "/api/gateway/v1/users/2/"
            },
            "summary_fields": {
                "modified_by": {
                    "id": 2,
                    "username": "admin",
                    "first_name": "",
                    "last_name": ""
                },
                "created_by": {
                    "id": 2,
                    "username": "admin",
                    "first_name": "",
                    "last_name": ""
                },
                "user": {
                    "id": 2,
                    "username": "admin",
                    "first_name": "",
                    "last_name": ""
                },
                "application": {
                    "id": 1,
                    "name": "My Test Application"
                }
            },
            "created": "2024-05-09T18:55:34.591523Z",
            "created_by": 2,
            "modified": "2024-05-09T18:55:34.608644Z",
            "modified_by": 2,
            "expires": "3023-09-10T18:55:34.587181Z",
            "user": 2,
            "application": 1,
            "description": "",
            "last_used": "2024-05-09T18:59:32.838553Z",
            "scope": "write",
            "token": "$encrypted$",
            "refresh_token": "$encrypted$"
        }
```
For an OAuth2 token, the only fully mutable fields are `scope` and `description`. The `application`
field is *immutable on update*, and all other fields are totally immutable, and will be auto-populated
during creation.
* `user` - this field corresponds to the user the token is created for
* `expires` will be generated according to the configuration setting `OAUTH2_PROVIDER`
* `token` and `refresh_token` will be auto-generated to be non-clashing random strings.  

Both application tokens and personal access tokens will be shown at the `/api/tokens/`
endpoint.  Personal access tokens can be identified by the `application` field being `null`.  

**On RBAC side:**
- A user will be able to create a token if they are able to see the related application;
- The System Administrator is able to see and manipulate every token in the system;
- Organization admins will be able to see and manipulate all tokens belonging to Organization
  members;
  System Auditors can see all tokens and applications
- Other normal users will only be able to see and manipulate their own tokens.
> Note: Users can only see the token or refresh-token _value_ at the time of creation ONLY.  

#### Using OAuth2 Token System for Personal Access Tokens (PAT)
The most common usage of OAuth2 is authenticating users. The `token` field of a token is used
as part of the HTTP authentication header, in the format `Authorization: Bearer <token field value>`.  This _Bearer_
token can be obtained by doing a curl to the `/o/token/` endpoint. For example:  
```
curl -ku <user>:<password> -H "Content-Type: application/json" -X POST \
-d '{"description":"My Client", "application":null, "scope":"write"}' \
https://<service>/api/users/1/personal_tokens/ | python -m json.tool
```
Here is an example of using that PAT to access an API endpoint using `curl`:
```
curl -H "Authorization: Bearer kqHqxfpHGRRBXLNCOXxT5Zt3tpJogn" http://<service>/api/credentials/
```

According to OAuth2 specification, users should be able to acquire, revoke and refresh an access
token. In DAB the equivalent, and easiest, way of doing that is creating a token, deleting
a token, and deleting a token quickly followed by creating a new one.

The specification also provides standard ways of doing this. RFC 6749 elaborates
on those topics, but in summary, an OAuth2 token is officially acquired via authorization using
authorization information provided by applications (special application fields mentioned above).
There are dedicated endpoints for authorization and acquiring tokens. The `token` endpoint
is also responsible for token refresh, and token revoke can be done by the dedicated token revoke endpoint.

In DAB, our OAuth2 system is built on top of
[Django Oauth Toolkit](https://django-oauth-toolkit.readthedocs.io/en/latest/), which provides full
support on standard authorization, token revoke and refresh. DAB implements them and puts related
endpoints under `/o/` endpoint. Detailed examples on the most typical usage of those endpoints
are available as description text of `/o/`. See below for information on Application Access Token usage.  
> Note: The `/o/` endpoints can only be used for application tokens, and are not valid for personal access tokens.  


#### Token Scope Mask Over RBAC System

The scope of an OAuth2 token is a space-separated string composed of keywords like 'read' and 'write'.
These keywords are configurable and used to specify permission level of the authenticated API client.
For the initial OAuth2 implementation, we use the most simple scope configuration, where the only
valid scope keywords are 'read' and 'write'.

Read and write scopes provide a mask layer over the RBAC permission system. In specific, a
'write' scope gives the authenticated user the full permissions the RBAC system provides, while 'read'
scope gives the authenticated user only read permissions the RBAC system provides.

For example, if a user has admin permission to an object, they can both see and modify, launch
and delete the object if authenticated via session or basic auth. On the other hand, if the user
is authenticated using OAuth2 token, and the related token scope is 'read', the user can only see but
not manipulate the object, despite being an admin. If the token scope is 'write' or 'read write', they
can take full advantage of the object as they are admin.  Note that 'write' implies 'read' as well.  


## Application Functions

This page lists OAuth2 utility endpoints used for authorization, token refresh and revoke.
Note endpoints other than `/o/authorize/` are not meant to be used in browsers and do not
support HTTP GET. The endpoints here strictly follow
[RFC specs for OAuth2](https://tools.ietf.org/html/rfc6749), so please use that for detailed
reference. Below are some examples to demonstrate the typical usage of these endpoints.


#### Application Using `authorization code` Grant Type

This application grant type is intended to be used when the application is executing on the server.  To create
an application named `AuthCodeApp` with the `authorization-code` grant type,
make a POST to the `/api/applications/` endpoint:
```text
{
    "name": "AuthCodeApp",
    "user": 1,
    "client_type": "confidential",
    "redirect_uris": "http://<service>/api/",
    "authorization_grant_type": "authorization-code",
    "skip_authorization": false
}
```
You can test the authorization flow out with this new application by copying the `client_id` and URI link into the
homepage [here](http://django-oauth-toolkit.herokuapp.com/consumer/) and click submit. This is just a simple test
application `Django-oauth-toolkit` provides.

From the client app, the user makes a GET to the Authorize endpoint with the `response_type`,
`client_id`, `redirect_uris`, and `scope`.  DAB will respond with the authorization `code` and `state`
to the `redirect_uri` specified in the application. The client application will then make a POST to the
`/o/token/` endpoint on DAB with the `code`, `client_id`, `client_secret`, `grant_type`, and `redirect_uri`.
DAB will respond with the `access_token`, `token_type`, `refresh_token`, and `expires_in`. For more
information on testing this flow, refer to [django-oauth-toolkit](http://django-oauth-toolkit.readthedocs.io/en/latest/tutorial/tutorial_01.html#test-your-authorization-server).


#### Application Using `password` Grant Type

This is also called the `resource owner credentials grant`. This is for use by users who have
native access to the web app. This should be used when the client is the Resource owner.  Suppose
we have an application `Default Application` with grant type `password`:
```text
{
    "id": 6,
    "type": "application",
    ...
    "name": "Default Application",
    "user": 1,
    "client_id": "gwSPoasWSdNkMDtBN3Hu2WYQpPWCO9SwUEsKK22l",
    "client_secret": "fI6ZpfocHYBGfm1tP92r0yIgCyfRdDQt0Tos9L8a4fNsJjQQMwp9569eIaUBsaVDgt2eiwOGe0bg5m5vCSstClZmtdy359RVx2rQK5YlIWyPlrolpt2LEpVeKXWaiybo",
    "client_type": "confidential",
    "redirect_uris": "",
    "authorization_grant_type": "password",
    "skip_authorization": false
}
```

Login is not required for `password` grant type, so we can simply use `curl` to acquire a personal access token
via `/o/token/`:
```bash
curl -X POST \
  -d "grant_type=password&username=<username>&password=<password>&scope=read" \
  -u "gwSPoasWSdNkMDtBN3Hu2WYQpPWCO9SwUEsKK22l:fI6ZpfocHYBGfm1tP92r0yIgCyfRdDQt0Tos9L8a4fNsJjQQMwp9569e
IaUBsaVDgt2eiwOGe0bg5m5vCSstClZmtdy359RVx2rQK5YlIWyPlrolpt2LEpVeKXWaiybo" \
  http://<service>/o/token/ -i
```
In the above POST request, parameters `username` and `password` are the username and password of the related
user of the underlying application, and the authentication information is of format
`<client_id>:<client_secret>`, where `client_id` and `client_secret` are the corresponding fields of
underlying application.

Upon success, the access token, refresh token and other information are given in the response body in JSON
format:
```text
HTTP/1.1 200 OK
Server: nginx/1.12.2
Date: Tue, 05 Dec 2017 16:48:09 GMT
Content-Type: application/json
Content-Length: 163
Connection: keep-alive
Content-Language: en
Vary: Accept-Language, Cookie
Pragma: no-cache
Cache-Control: no-store
Strict-Transport-Security: max-age=15768000

{"access_token": "9epHOqHhnXUcgYK8QanOmUQPSgX92g", "token_type": "Bearer", "expires_in": 315360000000, "refresh_token": "jMRX6QvzOTf046KHee3TU5mT3nyXsz", "scope": "read"}
```


## Token Functions

#### Refresh an Existing Access Token

Suppose we have an existing access token with refresh token provided:
```text
{
    "id": 35,
    "type": "access_token",
    ...
    "user": 1,
    "token": "omMFLk7UKpB36WN2Qma9H3gbwEBSOc",
    "refresh_token": "AL0NK9TTpv0qp54dGbC4VUZtsZ9r8z",
    "application": 6,
    "expires": "2017-12-06T03:46:17.087022Z",
    "scope": "read write"
}
```
The `/o/token/` endpoint is used for refreshing the access token:
```bash
curl -X POST \
  -d "grant_type=refresh_token&refresh_token=AL0NK9TTpv0qp54dGbC4VUZtsZ9r8z" \
  -u "gwSPoasWSdNkMDtBN3Hu2WYQpPWCO9SwUEsKK22l:fI6ZpfocHYBGfm1tP92r0yIgCyfRdDQt0Tos9L8a4fNsJjQQMwp9569eIaUBsaVDgt2eiwOGe0bg5m5vCSstClZmtdy359RVx2rQK5YlIWyPlrolpt2LEpVeKXWaiybo" \
  http://<service>/o/token/ -i
```
In the above POST request, `refresh_token` is provided by `refresh_token` field of the access token
above. The authentication information is of format `<client_id>:<client_secret>`, where `client_id`
and `client_secret` are the corresponding fields of underlying related application of the access token.

Upon success, the new (refreshed) access token with the same scope information as the previous one is
given in the response body in JSON format:
```text
HTTP/1.1 200 OK
Server: nginx/1.12.2
Date: Tue, 05 Dec 2017 17:54:06 GMT
Content-Type: application/json
Content-Length: 169
Connection: keep-alive
Content-Language: en
Vary: Accept-Language, Cookie
Pragma: no-cache
Cache-Control: no-store
Strict-Transport-Security: max-age=15768000

{"access_token": "NDInWxGJI4iZgqpsreujjbvzCfJqgR", "token_type": "Bearer", "expires_in": 315360000000, "refresh_token": "DqOrmz8bx3srlHkZNKmDpqA86bnQkT", "scope": "read write"}
```
Internally, the refresh operation deletes the existing token and a new token is created immediately
after, with information like scope and related application identical to the original one. We can
verify by checking the new token is present and the old token is deleted at the `/api/tokens/` endpoint.


#### Revoke an Access Token

##### Alternatively Revoke Using the /o/revoke-token/ Endpoint

Revoking an access token by this method is the same as deleting the token resource object, but it allows you to delete a token by providing its token value, and the associated `client_id` (and `client_secret` if the application is `confidential`).  For example:
```bash
curl -X POST -d "token=rQONsve372fQwuc2pn76k3IHDCYpi7" \
  -u "gwSPoasWSdNkMDtBN3Hu2WYQpPWCO9SwUEsKK22l:fI6ZpfocHYBGfm1tP92r0yIgCyfRdDQt0Tos9L8a4fNsJjQQMwp9569eIaUBsaVDgt2eiwOGe0bg5m5vCSstClZmtdy359RVx2rQK5YlIWyPlrolpt2LEpVeKXWaiybo" \
  http://<service>/o/revoke_token/ -i
```
`200 OK` means a successful delete.

We can verify the effect by checking if the token is no longer present
at `/api/tokens/`.


## Acceptance Criteria

* All CRUD operations for OAuth2 applications and tokens should function as described.
* RBAC rules applied to OAuth2 applications and tokens should behave as described.
* A default application should be auto-created for each new user.
* Incoming requests using unexpired OAuth2 token correctly in authentication header should be able
  to successfully authenticate themselves.
* Token scope mask over RBAC should work as described.
* DAB configuration setting `OAUTH2_PROVIDER` should be configurable and function as described.
* `/o/` endpoint should work as expected. In specific, all examples given in the description
  help text should be working (a user following the steps should get expected result).
