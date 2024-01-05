# We define these two wrapper functions because they are injected directly into the models migrations
# However, if oauth2_provider is not in INSTALLED_APPS (because we aren't enabling the OAUTH_PROVIDER feature)
#   then the migration fails because it can't load oauth2_provider.generators
# Having these wrapper gets us around that limitation


def generate_client_id():
    from oauth2_provider.generators import generate_client_id as oa2_gen_client_id

    return oa2_gen_client_id()


def generate_client_secret():
    from oauth2_provider.generators import generate_client_secret as oa2_gen_client_sec

    return oa2_gen_client_sec()
