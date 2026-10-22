# MS SQL Server Docker Volume Management

## Overview

The MS SQL Server development container uses a Docker named volume to persist database files. As of the latest update, the volume is automatically removed on teardown to ensure fresh database state during development.

## Behavior

### Before (Old Behavior)
```bash
make stop-mssql  # Stopped container but kept volume
# Volume persisted with migration state cached
# Next 'make mssql' reused old volume with stale data
```

**Problem:** Cached migration state prevented fresh migrations from running, causing "No migrations to apply" even after removing the container.

### After (Current Behavior)
```bash
make stop-mssql  # Stops container AND removes volume
# Volume completely removed
# Next 'make mssql' creates fresh volume
# Fresh database runs all migrations from scratch
```

**Solution:** Volume is removed on teardown, ensuring clean state for development.

## Commands

### Start MS SQL Server
```bash
make mssql
```
- Creates container if it doesn't exist
- Starts existing container if stopped
- Creates fresh volume if volume doesn't exist
- Database is ready when healthcheck passes

### Stop MS SQL Server
```bash
make stop-mssql
```
- Stops the container
- **Removes the data volume** (fresh DB on next start)
- Removes the network

### Check Volume Status
```bash
# List all volumes
docker volume ls

# Check for MS SQL volume specifically
docker volume ls | grep mssql

# If volume exists, you'll see:
# local     django-ansible-base_dab_mssql_data
```

## Migration Workflow

### Fresh Start (Recommended for Development)
```bash
# 1. Stop and clean up
make stop-mssql

# 2. Start fresh
make mssql

# 3. Wait for healthcheck (happens automatically)
sleep 5

# 4. Run migrations
python manage.py migrate

# All migrations run fresh ✓
```

### Persistent Data (Manual Override)
If you need to keep data between restarts for testing:

```bash
# Stop container but keep volume manually
docker stop dab_mssql

# Later, restart without recreating
docker start dab_mssql

# Data persists ✓
```

**Note:** This bypasses `make stop-mssql` which removes the volume.

## Files Modified

### Makefile
```makefile
## Stops the MS SQL Server container and removes data volume (fresh DB on next start)
stop-mssql:
	echo "Stopping dab_mssql container and removing data volume"
	$(DOCKER_COMPOSE) -f docker-compose.mssql.yml down -v
```

**Key change:** Added `-v` flag to `docker-compose down` to remove volumes.

### docker-compose.mssql.yml
```yaml
volumes:
  dab_mssql_data:
    # Named volume for MS SQL Server data files
    # Created automatically on 'make mssql'
    # Removed automatically on 'make stop-mssql' (down -v flag removes volumes)
```

**Key change:** Updated comments to reflect automatic volume removal.

## Why This Matters

### Development Benefits
1. **Fresh migrations every time** - No cached migration state
2. **Consistent testing** - Each test cycle starts from known state
3. **No manual cleanup** - `make stop-mssql` handles everything
4. **Faster debugging** - No need to manually remove volumes

### Migration Testing
When testing MS SQL Server compatibility:
```bash
# Clean slate every time
make stop-mssql && make mssql && sleep 5 && python manage.py migrate
```

This ensures:
- ✅ All migrations run fresh
- ✅ No stale migration state
- ✅ Accurate migration testing
- ✅ Reproducible results

## Troubleshooting

### "No migrations to apply" but database is empty
**Cause:** Volume persisted from previous run (old behavior)

**Fix:**
```bash
# Manually remove volume
docker volume rm django-ansible-base_dab_mssql_data

# Or use updated make target
make stop-mssql  # Now removes volume automatically
```

### Volume won't remove (in use)
**Cause:** Container still running

**Fix:**
```bash
# Force stop container first
docker stop dab_mssql
docker rm dab_mssql

# Then remove volume
docker volume rm django-ansible-base_dab_mssql_data

# Or use make target (handles this automatically)
make stop-mssql
```

### Want to keep data between restarts
**Solution:** Don't use `make stop-mssql`. Instead:
```bash
# Stop without removing
docker stop dab_mssql

# Restart later
docker start dab_mssql
```

## Production Considerations

**⚠️ WARNING:** This automatic volume removal is **DEVELOPMENT ONLY**.

In production:
- Use persistent volumes or host directories
- Never use `-v` flag on teardown
- Implement proper backup/restore procedures
- Use managed database services when possible

## See Also

- [MS SQL Server Compatibility](mssql-textfield-behavior.md)
- [JSONField Compatibility](mssql-jsonfield-compatibility.md)
- [docker-compose.mssql.yml](../docker-compose.mssql.yml)
- [Makefile](../Makefile)
