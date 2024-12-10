# .githooks

This folder contains executable files that will be invoked by git at certain git operations.

By default git hooks are located i `.git/hooks` folder at the root of the repository. Since the default folder is hidden by most IDEs, this repository reconfigures git's hook location in order to make the hooks visible and easier to maintain.

## Configuration

Normal development flows (see file [../README.md](../README.md) ) will call git to change the location of git hooks.

To make this change manually you can invoke following command from the root of the repository:

```sh
make git_hooks_config
```

## Git hooks implementation

Git hooks are simply executable files that follow the rules below:

* have executable permissions
* file name must correspond to git hook name with no extension(no `.sh` or `.py`) (see documentation section below)

Return code other than zero(0) will cause the git operation that triggerred the hook to fail, while zero(0) return code indicates success and git opertaion will succeed.

## Documentation

Git hooks documentation: <https://git-scm.com/docs/githooks>
