# Organizations

The django-ansible-base project provides the 
`ansible_base.lib.abstract_models.organization.AbstractOrganization` base class. Projects that implement 
organizations MUST inherit this model.

The `AbstractOrganization` has the following fields:

* `name` – A unique name of the organization (maximum 512 characters),
* `description` – A description of the organization,
* `users` – A many to many relationship to the user model (defined by the `AUTH_USER_MODEL` setting),
* `teams` – A many to many relationship to the team model (defined by the `ANSIBLE_BASE_TEAM_MODEL` setting),

for the list of remaining fields see `ansible_base.lib.abstract_models.common.CommonModel`.

The user and the team models will receive an additional field named `organizations`, that references
related organizations of a respective model.

## Configuration

The `ANSIBLE_BASE_TEAM_MODEL` setting is mandatory and must be defined in django settings. 
It must be of the format `<app_label>.<model_name>`.

Example:

```python
ANSIBLE_BASE_TEAM_MODEL = 'example.Team'
```
