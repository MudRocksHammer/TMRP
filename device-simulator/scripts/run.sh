#!/usr/bin/env bash
set -euo pipefail
simulator_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
qt_prefix="${TMRP_QT_PREFIX:-$simulator_root/.deps/qt/usr}"
cmake_bin=cmake
cmake_options=()
if [[ -x "$qt_prefix/bin/cmake" ]]; then
    cmake_bin="$qt_prefix/bin/cmake"
    export LD_LIBRARY_PATH="$qt_prefix/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    export QT_PLUGIN_PATH="$qt_prefix/lib/x86_64-linux-gnu/qt6/plugins"
    if [[ -f "$qt_prefix/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc" ]]; then
        export TMRP_SIMULATOR_FONT="$qt_prefix/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
    fi
    cmake_options=("-DCMAKE_PREFIX_PATH=$qt_prefix" "-DCMAKE_INCLUDE_PATH=$qt_prefix/include" "-DCMAKE_LIBRARY_PATH=$qt_prefix/lib/x86_64-linux-gnu")
fi
# Qt/C++アプリのビルド設定を作成する
"$cmake_bin" -S "$simulator_root" -B "$simulator_root/build" -DCMAKE_BUILD_TYPE=Debug "${cmake_options[@]}"
# メモリ使用量を抑え、2並列でビルドする
"$cmake_bin" --build "$simulator_root/build" --parallel 2
# 引数をそのままアプリへ渡して起動する
exec "$simulator_root/build/tmrp-device-simulator" "$@"
