from setuptools import find_packages, setup

extra_setup_args = {}

setup(
    name='django-ansible-base',
    version="0.1",
    description='A Django app used by ansible services',
    author='Red Hat, Inc.',
    author_email='info@ansible.com',
    url='https://github.com/ansible/django-ansible-base',
    packages=find_packages(exclude=['test']),
    include_package_data=True,
    install_requires=[
        'PyYAML',
        'requests',
        'django>=4.2,<4.3'
        # TODO: Populate with the rest of the stuff django-restframework, social_auth, etc.
    ],
    python_requires=">=3.11",
    extras_require={},
    license='Apache 2.0',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Environment :: Web Environment',
        'Framework :: Django',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'Operating System :: OS Independent',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3.11',
    ],
    **extra_setup_args,
)
