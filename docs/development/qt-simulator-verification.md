# C++/Qt模擬設備の検証記録

検証日：2026-10-30。Windows/Linux対応・複数設備管理の追加に対する記録。

## 環境と結果

Ubuntu 24.04、GCC 13.3、CMake 3.28.3、Qt 6.4.2、libmosquitto 2.0.18でビルドした。
Qtは管理者権限を使わずUbuntuパッケージをローカル展開した。GUIテストはoffscreenで実行した。

| 検証 | 結果・対象 |
|---|---|
| C++ビルド | 成功 |
| CTest `device_engine` | 成功：遥測、指令の検証、重複・競合、状態保存・再起動 |
| CTest `control_window` | 成功：ローカル操作、画面と設備状態の連動 |
| CTest `fleet_management` | 成功：追加・編集・削除・再読込、設備状態の分離、IP設定、不正設定、保存失敗時の復元 |
| 実通信統合試験 | 成功：同一Qtプロセス内の2設備→実Mosquitto→Python受信器→PostgreSQL |
| 指令送信スクリプト | 統合試験で新規指令と保存済み指令の再送を確認 |
| Python静的検査 | Ruff lint・format成功 |
| Linux画面 | 日本語フォントを含むスクリーンショットで表示確認 |
| Windows | MSVC用ビルドスクリプトとGitHub Actionsを追加。Windowsでの実行は未検証 |

実通信試験では、設備001はループバックのMQTT、設備002はテスト証明書付きTLSを使用した。
送信元IPを明示し、両設備のDB保存、同じ指令IDでも設備間で干渉しないこと、重複指令・内容競合、
アプリ再起動後の状態復元、Broker再起動後の復旧を確認した。
専用ポート・一時フォルダー・ランダム名のDBスキーマを使用し、終了時に削除する。
既存サービスの設定・既存テーブルを変更する試験ではない。

## 再実行

通常のQtインストール環境ではTMRPルートから実行する。

```bash
# C++アプリとQtTestをビルドする
cmake -S device-simulator -B device-simulator/build -DCMAKE_BUILD_TYPE=Debug
cmake --build device-simulator/build --parallel 2
# 設備モデル・GUI・複数設備管理の3スイートを実行する
ctest --test-dir device-simulator/build --output-on-failure
# テスト用スキーマを作成できる開発DB接続先を指定する
export TMRP_TEST_DSN='host=/var/run/postgresql dbname=tmrp_dev user=shou'
# 実BrokerとQtアプリを起動し、受信器・DB・指令の往復を検証する
.venv/bin/python device-simulator/tests/integration_mqtt.py
# Python補助スクリプトと統合試験の静的検査を行う
.venv/bin/python -m ruff check device-simulator/scripts device-simulator/tests
.venv/bin/python -m ruff format --check device-simulator/scripts device-simulator/tests
```

統合試験にはMosquitto、OpenSSL、起動済みPostgreSQLとプロジェクトのPython依存関係が必要。
WindowsからVMへ渡る実際のネットワーク経路、および64台・各50Hzの負荷は今回の合格範囲に含めない。
Windows側での確認は[VM接続ガイド](../guides/qt-simulator-vm.md)に従う。

## Windows自動セットアップの追加検証（2026-10-31）

`scripts/setup-windows.ps1`を追加し、既存の`build-windows.ps1`でローカル設定を読み込めるようにした。
Linux上のPowerShell 7.4.6で`tests/test_windows_setup.ps1`を実行し、次を確認した。

- PowerShellスクリプトの構文解析。
- VS 2022／2026のgenerator選択、2026でのCMake 4.2要件、VS別のビルド出力先、未対応バージョンの拒否。
- Qtキットの不足ファイル、MSVCライブラリ欠如、ARM64の拒否、およびMSVC x64相当のfixtureの受理。
- 外部コマンドの成功と、非ゼロ終了コードを伴う例外による停止。

```powershell
# インストールやネット接続を伴わず、セットアップ補助処理をテストする
pwsh -NoProfile -File device-simulator/tests/test_windows_setup.ps1
```

Windowsでのwinget・UAC・初回ダウンロード・C++ビルド全体はこの環境では実行していない。
VS 2026の検出・生成方式を追加したが、VS 2026実機でのコンパイル・DLL配置は未検証。
文字化けによる解析エラーの報告を受け、旧スクリプトのUTF-8本文を.NETのCP936としてデコードした場合に、
`UnexpectedToken`、`TerminatorExpectedAtEndOfString`、`MissingEndCurlyBrace`を再現した。
Windows用スクリプトをASCIIへ統一し、CP936／CP1252で読み取った場合の構文解析を回帰テストへ追加した。
実行済みテストはLinux上のPowerShell 7。Windows PowerShell 5.1での検査もCIへ追加したが、CIは今回未実行。
Windows CIはセットアップスクリプト経由で導入済みQt/vcpkgを使う構成へ変更したが、今回の作業中にCIは実行していない。
