# Data validation

django-ansible-base provides some basic validation tools. These reside in `ansible_base.lib.utils.validation`.
The following items are available from the validation library:

`ansible_base.lib.utils.validation.VALID_STRING` this is a common string which says say:
```
Must be a valid string
```

`ansible_base.lib.utils.validation.validate_url` this is similar to the validate_url in django but has a parameter for `allow_plain_hostname: bool = False` which means you can have a url like `https://something:443/testing`.

`ansible_base.lib.utils.validation.validate_url_list` this is a convince method which takes an array of urls and validates each of them using its own validate_url method. 
