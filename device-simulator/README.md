# TMRP Device Simulator

C++17 / Qt 6 Widgets / libmosquitto / SQLiteで作成した、電力回線の模擬設備アプリ。
Windows x64とLinuxを対象に、同じCMakeプロジェクトをビルドする。

## できること

- 設備の追加、編集、一覧からの削除、JSONでの保存・再読込（最大64台）。
- 設備別のBroker IP・ポート、送信元IP、認証、TLS、送信頻度、模擬動作時間。
- 個別／一括の接続・定期送信・停止。既定の送信頻度は1 Hz。
- 電圧・電流・力率・周波数・測定欠損の設定、遮断器のローカル開閉。
- 遠方操作許可・操作インターロック、指令JSON・受付・完了・拒否理由の表示。
- 機器別SQLiteへの状態・指令結果保存、同じ指令IDの重複実行防止、未送信結果の再送。

設備はそれぞれ独立したMQTT接続・タイマー・boot_id・連番・SQLiteを持つ。
機器IDは一覧内で一意。既存台帳には`power-meter-001`〜`012`が登録済み。
新しい機器IDを作る場合はサーバーの`examples/power/assets.json`にも追加して受信器を再起動する。

「Broker IP」は接続先。「送信元IP」はアプリを動かすPCのネットワークインターフェースへ既に割り当てられたIPに限る。
通常は送信元IPを空欄にし、複数設備を機器IDで識別する。設備の追加でOS上のIPや仮想NICは増えない。

## Linuxでビルド・起動

Ubuntu 24.04の例。TMRPルートから実行する。

```bash
# C++、Qt、MQTTと日本語表示に必要な開発パッケージを導入する
sudo apt update
sudo apt install build-essential cmake qt6-base-dev libqt6sql6-sqlite libmosquitto-dev fonts-noto-cjk
# 設定・ビルドを行い、複数設備管理画面を起動する
bash device-simulator/scripts/run.sh
```

この作業環境では管理者権限がないため、同じUbuntuパッケージを`.deps/qt/`に展開して検証した。
起動スクリプトはこのローカル配置があれば自動的に使用する。`.deps/`と`build*/`はGitへ含めない。
別PCでは上記の通常インストールを行う。Qt Creatorで`CMakeLists.txt`を開く方法も使える。

```bash
# 通常インストール環境でCMakeを直接使う場合
cmake -S device-simulator -B device-simulator/build -DCMAKE_BUILD_TYPE=Debug
cmake --build device-simulator/build --parallel 2
# Qtの設備モデル・操作画面・複数設備管理テストを実行する
ctest --test-dir device-simulator/build --output-on-failure
```

## Windowsでビルド・起動

### 自動セットアップ

Windows x64の通常のPowerShellから実行できる。Windows側へ最新の`device-simulator`をコピーしておく。
初回はネット接続と、インストーラーが要求する管理者権限（UAC）が必要。
`winget`がない場合はMicrosoftの「アプリ インストーラー」を導入・更新してから実行する。

```powershell
# Windows側のTMRPへ移動する（実際の保存先に変更する）
cd C:\dev\TMRP
# セットアップ・ビルド・テスト・DLL配置を実施し、成功後にアプリを開く
# ExecutionPolicyはこのPowerShellプロセスだけに適用する
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\device-simulator\scripts\setup-windows.ps1 -Launch
```

スクリプトはGit、Visual Studio 2022／2026のC++ツール、CMakeを確認する。
既存のVS Community／Professional／Enterprise／Build Toolsから、C++機能がある新しいバージョンを優先する。
VS自体がない場合はVS 2022 Build Toolsをwingetで導入する。VSがあるのにC++機能がない場合は、
別のVSを追加せず「Visual Studio Installer → 変更 → C++によるデスクトップ開発」の追加を案内して停止する。
Git・対応CMakeの不足分もwingetで導入する。
Qtがない場合はPythonと専用venvのaqtinstall 3.3.0を使い、Qt 6.8.3のMSVC x64キットを取得する。
vcpkgを取得・初期化し、MosquittoなどのC++依存関係はCMake設定時に導入する。
Qt Creatorは導入しない。Qtのバージョンは`-QtVersion`で指定できる（MSVC 2022 x64キットが必要）。
wingetのソース・パッケージ規約への同意オプションを使う。Qtの取得は第三者ツールaqtinstallを経由する。

既定の保存先は`%LOCALAPPDATA%\TMRP\toolchains`。`-InstallRoot C:\dev\tmrp-tools`で変更できる。
既存のQtは`QT_ROOT_DIR`、`C:\Qt\<バージョン>\msvc2022_64`、保存先の順で探す。
既存vcpkgは`VCPKG_ROOT`または`VCPKG_INSTALLATION_ROOT`からも取得する。
独自の場所へ導入済みの場合は明示する。

```powershell
# 既存のQtとvcpkgを使う
& .\device-simulator\scripts\setup-windows.ps1 `
  -QtPrefix C:\Qt\6.8.3\msvc2022_64 -VcpkgRoot C:\dev\vcpkg -Launch
# 環境の準備だけ行う（アプリのビルド・C++依存関係の導入は後で行う）
& .\device-simulator\scripts\setup-windows.ps1 -SetupOnly
# 2回目以降は保存されたパスでビルド・テストする
& .\device-simulator\scripts\build-windows.ps1
# アプリを起動する
& .\device-simulator\build-windows\Release\tmrp-device-simulator.exe
```

**Visual Studio 2026 Communityを使う場合**は、InstallerでMSVC x64/x86ビルドツール、Windows SDK、
C++ CMakeツールを含む「C++によるデスクトップ開発」を導入してから、同じセットアップコマンドを実行する。
VS 2026ではCMake 4.2以降と`Visual Studio 18 2026`を使用し、
出力先は`build-windows-vs2026\Release\tmrp-device-simulator.exe`になる。
VS 2022の既存ビルドキャッシュはそのまま残す。`-Launch`は選択したVSの出力を起動する。
直接ビルドするときも保存したVSのパスを使い、`-VisualStudioPath`で変更できる。

Qtキット名の`msvc2022_64`はQtのビルドに使われたコンパイラーを示し、IDEを必ず2022にする意味ではない。
VS 2026との組合せは[MicrosoftのMSVCバイナリ互換性](https://learn.microsoft.com/en-us/cpp/porting/binary-compat-2015-2017?view=msvc-170)
を根拠に利用する構成。ただしQt 6.8の公式対応表はMSVC 2022であり、VS 2026での本アプリの実ビルドは未検証。
CMake要件は[公式VS 2026 generator資料](https://cmake.org/cmake/help/latest/generator/Visual%20Studio%2018%202026.html)を参照。
古いvcpkgでVS 2026を認識できない場合は、最新のvcpkgを別フォルダーへ取得して`-VcpkgRoot`で指定する。

使用したパスは`.deps/windows-toolchain.json`へ保存し、Gitには含めない。
スクリプト自身は永続PATHやシステムの実行ポリシーを変更しない。各ツールのインストーラーがPATHを追加する場合はある。
既存のvcpkgを勝手に更新せず、失敗したコマンドでは処理を止める。
再起動が必要と表示された場合はWindowsを再起動して同じコマンドを実行する。
既存のQt/vcpkgが正常なら再利用する。通信失敗や不完全なインストールが残った場合は、表示された対象を修復して再実行する。

`Saved local build settings`の後に`UnexpectedToken`や「文字列の終端がない」が出て日本語も文字化けする場合は、
古い`build-windows.ps1`のUTF-8がWindows PowerShell 5.1で誤読されている可能性がある。
現行のWindows用スクリプトはコメント・メッセージもASCIIへ統一した。
修正版の`build-windows.ps1`をコピーし、保存済み設定を使ってビルドだけ再実行する。

```powershell
# セットアップ済みの環境で、ビルドから再開する
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\device-simulator\scripts\build-windows.ps1
```

セットアップ補助関数はPowerShell上でテスト済み。Windowsでの初回インストール全体は未検証。
GitHub ActionsのWindowsジョブでは導入済みQt/vcpkgを使う経路を検証する構成にしている。
参考：[MicrosoftのVS自動導入](https://learn.microsoft.com/en-us/visualstudio/install/use-command-line-parameters-to-install-visual-studio?view=vs-2022)、
[aqtinstallのコマンド](https://aqtinstall.readthedocs.io/en/latest/cli.html)。

### 手動で準備する場合

1. Visual Studio 2022または2026の「C++によるデスクトップ開発」とWindows SDK、CMake、Gitを用意する。VS 2026はCMake 4.2以降が必要。
2. Qt 6.4以降の**MSVC 2022 64-bit**キットを導入する。下記はQt 6.8.3のパス例。
3. vcpkgを準備する。MinGW版QtとMSVCライブラリを混在させない。
4. 使用するVSの**Developer PowerShell**でTMRPルートへ移動して実行する。下記のexeパスはVS 2022の場合。

```powershell
# vcpkgをまだ用意していない場合。既存の導入先があればそれを使う
git clone https://github.com/microsoft/vcpkg C:\dev\vcpkg
& C:\dev\vcpkg\bootstrap-vcpkg.bat
# 実際のQt導入先を指定し、CMake設定・ビルド・テスト・Qt DLL配置を行う
& .\device-simulator\scripts\build-windows.ps1 `
  -QtPrefix C:\Qt\6.8.3\msvc2022_64 `
  -VcpkgRoot C:\dev\vcpkg
# 模擬設備マネージャーを起動する
& .\device-simulator\build-windows\Release\tmrp-device-simulator.exe
```

`vcpkg.json`はlibmosquittoとTLS依存関係を導入する。Qtは上記キットを使用する。
vcpkgのCMake targetがDebug/Releaseのリンク先を選び、実行に必要なMQTT/OpenSSL DLLをビルド先へ配置する。
`windeployqt`でQt DLLとplatforms・SQLite等のプラグインを配置する。配布時はexeだけでなく配置されたフォルダー一式を渡す。

Windows実機でのビルド・実行結果はLinuxでの検証とは区別する。
今回の[検証結果と再実行方法](../docs/development/qt-simulator-verification.md)を参照。
手順の根拠：[Qt Windows配布](https://doc.qt.io/qt-6/windows-deployment.html)、
[vcpkgのMosquitto target](https://github.com/microsoft/vcpkg/blob/master/ports/mosquitto/usage)。

## 操作手順

1. 「設備を追加」で機器ID・設備ID・Broker IP・ポートなどを設定する。
2. 一覧で設備を選び、「接続」→「定期送信を開始」。一括ボタンでも操作できる。
3. 「開く／閉じる」で模擬状態を変更する。開くと電流・有効電力は0、電源側電圧は残る。
4. 指令Topicに届いた指令は、その機器の履歴に表示される。行を選ぶとJSONを確認できる。
5. 接続設定の編集は接続・送信・指令操作を止めてから行う。機器ID・設備IDは追加後に変更せず、別設備として追加する。

一覧の変更は自動保存される。削除は一覧からの削除であり、SQLiteの設備状態・指令履歴は残る。
同じIDを再追加すると保存済み状態を使用する。
パスワードは画面で入力し、設定ファイルには保存しない。共通パスワードを使う場合は環境変数`TMRP_SIMULATOR_PASSWORD`を利用できる。

既定保存先はQtの`AppLocalDataLocation`。場所を明示したい場合：

```bash
# 設備一覧とSQLiteの保存先を明示して起動する
bash device-simulator/scripts/run.sh --state-dir ./device-simulator/local-state
# コピーした設備一覧を読み、全設備へ接続して送信を開始する
bash device-simulator/scripts/run.sh --fleet /path/to/devices.json --auto-connect --auto-send
# 従来の単一設備用INIを使用する場合（複数設備画面にはならない）
bash device-simulator/scripts/run.sh --config device-simulator/config/local.ini
```

## 遥測と指令

遥測は既存の[電力契約](../docs/reference/power-telemetry-contract.md)の16項目に準拠する。
連番は観測ごとに増加し、通信再接続ではboot_idを維持、アプリ再起動で新しくする。
電力値は平衡三相の簡易式で算出し、詳細な設備物理モデルは持たない。

| Topic | 用途 |
|---|---|
| `tmrp/devices/{device_id}/telemetry` | 電力遥測、QoS 1、retainなし |
| `tmrp/devices/{device_id}/commands` | 開閉指令の購読、QoS 1 |
| `tmrp/devices/{device_id}/command-results` | 指令の受付・拒否・完了・失敗 |
| `tmrp/devices/{device_id}/status` | online・Willによるoffline通知。最終遥測時刻と併用 |

指令JSONの例。時刻は送信時のUTCへ置き換える。有効期間は最大300秒。

```json
{
  "schema_version": "1.0",
  "message_type": "command",
  "command_id": "example-open-001",
  "device_id": "power-meter-001",
  "equipment_id": "breaker-001",
  "operation": "open_breaker",
  "issued_at": "2026-10-30T10:00:00Z",
  "expires_at": "2026-10-30T10:01:00Z"
}
```

操作は`open_breaker`と`close_breaker`。任意の`expected_state_version`で状態版の一致を要求できる。
受付後、設定した動作時間で状態・結果を同一SQLiteトランザクションで確定する。
同一ID・同一内容は保存済み結果を返し、同一ID・異なる内容は拒否する。
実行途中にアプリが停止した指令は、再起動後に`failed / device_restarted`になる。

## 制約

- MQTT PUBACKは設備の操作完了でも、サーバーDBへの保存完了でもない。操作完了は`command-results`で確認する。
- QoS 1の通信ACKと指令のローカル保存は不可分ではない。送信側はアプリ応答を待ち、未応答なら同じID・同じ本文で再送する。
- clean sessionを使用する。切断中の指令をBrokerへ長期間滞留させない。未応答の操作を別IDで再発行すると別指令になる。
- 遥測はディスクへ全件蓄積しない。切断中の送信を見送り、再接続後に現在値から再開する。
- UI履歴は最新500行、未確認送信は100件、指令受信待ちは128件、保存指令は10,000件を上限とする。指令履歴の自動削除は未実装。
- TLSはCA検証とホスト名／IP検証を行う。遠隔Brokerの平文接続は拒否する。SSHトンネルはループバック接続として利用できる。
- Python側にはまだ操作API・操作結果のDB保存機能がない。現在はテスト用送信器で操作し、MQTT上で結果を確認する。
- 64台・各50Hzは設定の上限であり、性能保証ではない。現在の基準負荷は12台×1Hz。

VMware上のUbuntuサーバーへの具体的な接続方法は[VM接続ガイド](../docs/guides/qt-simulator-vm.md)を参照する。
