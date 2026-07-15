# Game config updater

This updater imports dictionaries from an unpacked/exported Alipay mini-program
resource directory. It does not decrypt the Alipay mini-program cache itself.

For the Web/Cocos package captured under `login-output/package`, static DB files
can be downloaded from the versioned resource server recorded in `game.js`:

```powershell
npm run update-game-config -- "..\login-output" --scope db --dry-run
npm run update-game-config -- "..\login-output" --scope db
```

Web/Cocos protocol extraction is not yet supported; use `--scope db` for this
source format. `AttributeDB.json` and `EquipmentQualityDB.json` are retained
because the current Web build does not publish them as independent tables.

Run discovery and validation first:

```powershell
npm run update-game-config -- "D:\path\to\exported-game" --dry-run
```

Update all static DB and protocol dictionaries:

```powershell
npm run update-game-config -- "D:\path\to\exported-game"
```

Update only one group:

```powershell
npm run update-game-config -- "D:\path\to\exported-game" --scope db
npm run update-game-config -- "D:\path\to\exported-game" --scope grpc
```

The script recursively discovers the source directories, validates JSON and
protobuf content, and saves the previous files under `.game-config-backups/`
before replacing them. The gRPC JSON files and protobuf directory are replaced
together because they must come from the same game version.
