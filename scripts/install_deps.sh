#!/usr/bin/env bash
# AutoPilot Platform 新设备一键安装（macOS / Linux）。
# 默认安装全部：Platform Web、Runner 宿主工具、JDK/Node/Appium/Python。
# 本仓库 resources/ 已有的二进制一律跳过。
#
# 用法:
#   ./scripts/install_deps.sh
#   ./scripts/install_deps.sh --skip-appium --skip-init
#   ./scripts/install_deps.sh --check

set -euo pipefail

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
DIM='\033[2m'
NC='\033[0m'

SKIP_PYTHON=false
SKIP_APPIUM=false
SKIP_FRONTEND=false
SKIP_INIT=false
WITH_PLAYWRIGHT=false
WITH_REMOTE=false
WITH_ALL_PYTHON=false
CHECK_ONLY=false
for arg in "$@"; do
    case "${arg}" in
        --skip-python) SKIP_PYTHON=true ;;
        --skip-appium) SKIP_APPIUM=true ;;
        --skip-frontend) SKIP_FRONTEND=true ;;
        --skip-init) SKIP_INIT=true ;;
        --playwright|--with-playwright) WITH_PLAYWRIGHT=true ;;
        --remote|--with-remote) WITH_REMOTE=true ;;
        --all-python) WITH_ALL_PYTHON=true ;;
        --check|--check-only) CHECK_ONLY=true ;;
        -h|--help)
            sed -n '1,11p' "$0"
            exit 0
            ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOCAL_RES="${ROOT_DIR}/resources"
cd "${ROOT_DIR}"

OS_TYPE="$(uname -s)"
ARCH_TYPE="$(uname -m)"
NODE_VER="v22.23.2"
MIN_NODE_MAJOR=18
MIN_JAVA_MAJOR=17

has_cmd() {
    command -v "$1" >/dev/null 2>&1
}

normalize_path() {
    local STANDARD_PATHS=(
        "/opt/homebrew/bin"
        "/usr/local/bin"
        "${HOME}/.local/bin"
        "${HOME}/.local/share/node/bin"
        "${HOME}/.local/share/platform-tools"
        "${HOME}/Library/Android/sdk/platform-tools"
        "${HOME}/Android/Sdk/platform-tools"
    )
    local p
    for p in "${STANDARD_PATHS[@]}"; do
        if [ -d "${p}" ] && [[ ":${PATH}:" != *":${p}:"* ]]; then
            export PATH="${p}:${PATH}"
        fi
    done
}

local_resource() {
    [ -e "${LOCAL_RES}/$1" ]
}

adb_zip_name() {
    case "${OS_TYPE}" in
        Darwin) echo "platform-tools-latest-darwin.zip" ;;
        *) echo "platform-tools-latest-linux.zip" ;;
    esac
}

aapt_zip_name() {
    case "${OS_TYPE}" in
        Darwin) echo "aapt-macos.zip" ;;
        *) echo "aapt-linux.zip" ;;
    esac
}

go_ios_bin() {
    case "${OS_TYPE}" in
        Darwin) echo "re_go_ios/executable/mac/ios" ;;
        *) echo "re_go_ios/executable/linux/ios" ;;
    esac
}

node_major() {
    has_cmd node || { echo 0; return; }
    node -v 2>/dev/null | tr -d 'v' | cut -d. -f1
}

java_major() {
    has_cmd java || { echo 0; return; }
    local raw
    raw="$(java -version 2>&1 || true)"
    if echo "${raw}" | grep -Eq 'version "1\.'; then
        echo "${raw}" | sed -n 's/.*version "1\.\([0-9]*\).*/\1/p' | head -n1
        return
    fi
    echo "${raw}" | sed -n 's/.*version "\([0-9]*\).*/\1/p' | head -n1
}

node_ready() {
    local maj
    maj="$(node_major)"
    [ "${maj:-0}" -ge "${MIN_NODE_MAJOR}" ] && has_cmd npm
}

install_portable_adb() {
    has_cmd adb && return 0
    local os_sys
    os_sys="$(echo "${OS_TYPE}" | tr '[:upper:]' '[:lower:]')"
    [ "${os_sys}" = "darwin" ] || [ "${os_sys}" = "linux" ] || return 1
    local pt_dir="${HOME}/.local/share/platform-tools"
    if [ ! -x "${pt_dir}/adb" ]; then
        echo -e "   ${CYAN}内置 re_adb 不在仓库中，安装用户态 platform-tools...${NC}"
        mkdir -p "${HOME}/.local/share" "${HOME}/.local/bin"
        local zip="/tmp/platform-tools-$$.zip"
        if curl -fsSL --connect-timeout 8 --max-time 90 \
            "https://dl.google.com/android/repository/platform-tools-latest-${os_sys}.zip" -o "${zip}"; then
            if has_cmd unzip; then
                unzip -q -o "${zip}" -d "${HOME}/.local/share" || true
            else
                python3 -m zipfile -e "${zip}" "${HOME}/.local/share" 2>/dev/null || true
            fi
            rm -f "${zip}"
        fi
    fi
    if [ -x "${pt_dir}/adb" ]; then
        ln -sf "${pt_dir}/adb" "${HOME}/.local/bin/adb"
        export PATH="${pt_dir}:${PATH}"
        echo -e "   ${GREEN}✓ adb 已装到用户目录（未写入 resources/）${NC}"
        return 0
    fi
    echo -e "   ${YELLOW}⚠ 便携 adb 失败，且仓库 resources/re_adb 不可用${NC}"
    return 1
}

install_portable_node() {
    node_ready && return 0
    local node_arch=""
    case "${ARCH_TYPE}" in
        x86_64|amd64) node_arch="x64" ;;
        aarch64|arm64) node_arch="arm64" ;;
    esac
    local os_sys
    os_sys="$(uname -s | tr '[:upper:]' '[:lower:]')"
    [ -n "${node_arch}" ] || return 1
    local node_dir="${HOME}/.local/share/node"
    echo -e "   ${CYAN}安装便携 Node.js ${NODE_VER}...${NC}"
    mkdir -p "${node_dir}" "${HOME}/.local/bin"
    if curl -fsSL --connect-timeout 8 --max-time 90 \
        "https://nodejs.org/dist/${NODE_VER}/node-${NODE_VER}-${os_sys}-${node_arch}.tar.gz" \
        | tar -xz -C "${node_dir}" --strip-components=1; then
        ln -sf "${node_dir}/bin/node" "${HOME}/.local/bin/node"
        ln -sf "${node_dir}/bin/npm" "${HOME}/.local/bin/npm"
        ln -sf "${node_dir}/bin/npx" "${HOME}/.local/bin/npx"
        export PATH="${node_dir}/bin:${HOME}/.local/bin:${PATH}"
        echo -e "   ${GREEN}✓ 便携 Node.js ${NODE_VER} 已就绪${NC}"
        return 0
    fi
    return 1
}

ensure_node() {
    node_ready && return 0
    export NVM_DIR="${HOME}/.nvm"
    if [ -s "${NVM_DIR}/nvm.sh" ]; then
        # shellcheck disable=SC1090
        . "${NVM_DIR}/nvm.sh" 2>/dev/null || true
        nvm use 22 >/dev/null 2>&1 || true
    fi
    if ! node_ready && [ "${OS_TYPE}" = "Darwin" ] && has_cmd brew; then
        brew install node || brew upgrade node || true
    fi
    if ! node_ready; then
        install_portable_node || true
    fi
    node_ready
}

install_jdk() {
    local maj
    maj="$(java_major)"
    if [ "${maj:-0}" -ge "${MIN_JAVA_MAJOR}" ]; then
        echo -e "   ${GREEN}✓ Java 已就绪${NC}"
        return 0
    fi
    if [ "${OS_TYPE}" = "Darwin" ] && has_cmd brew; then
        brew install openjdk@17 || true
        if [ -d "/opt/homebrew/opt/openjdk@17" ]; then
            export JAVA_HOME="/opt/homebrew/opt/openjdk@17"
            export PATH="${JAVA_HOME}/bin:${PATH}"
        fi
    elif [ "${OS_TYPE}" = "Linux" ] && has_cmd sudo; then
        if has_cmd apt-get; then
            sudo apt-get install -y -qq openjdk-17-jdk || true
        elif has_cmd dnf; then
            sudo dnf install -y java-17-openjdk-devel || true
        fi
    fi
    maj="$(java_major)"
    [ "${maj:-0}" -ge "${MIN_JAVA_MAJOR}" ]
}

install_appium_stack() {
    ensure_node || {
        echo -e "   ${RED}✗ Node.js 未就绪，跳过 Appium${NC}"
        return 1
    }
    if ! has_cmd appium; then
        echo -e "   ${CYAN}npm install -g appium ...${NC}"
        npm install -g appium --no-fund --no-audit
    fi
    has_cmd appium || return 1
    echo -e "   ${GREEN}✓ Appium $(appium --version)${NC}"
    appium driver install uiautomator2 || true
    if [ "${OS_TYPE}" = "Darwin" ]; then
        appium driver install xcuitest || true
    fi
}

install_frontend() {
    ensure_node || return 1
    local frontend="${ROOT_DIR}/autopilot_platform/frontend"
    if [ ! -f "${frontend}/package.json" ]; then
        echo -e "   ${YELLOW}⚠ 未找到 frontend/package.json${NC}"
        return 1
    fi
    echo -e "   ${CYAN}npm install (frontend) ...${NC}"
    (cd "${frontend}" && npm install --no-fund --no-audit)
}

python_spec() {
    local parts=("dev" "runner")
    if [ "${WITH_REMOTE}" = true ] || [ "${WITH_ALL_PYTHON}" = true ]; then
        parts+=("runner_remote")
    fi
    if [ "${WITH_PLAYWRIGHT}" = true ] || [ "${WITH_ALL_PYTHON}" = true ]; then
        parts+=("web_playwright")
    fi
    if [ "${WITH_ALL_PYTHON}" = true ]; then
        parts+=("s3" "pg" "secure")
    fi
    local IFS=,
    echo ".[${parts[*]}]"
}

install_python_env() {
    local py=""
    if has_cmd python3; then
        py="python3"
    elif has_cmd python; then
        py="python"
    else
        echo -e "   ${RED}✗ 未找到 Python 3.10+${NC}"
        return 1
    fi
    if [ ! -x "${ROOT_DIR}/.venv/bin/python" ]; then
        echo -e "   ${CYAN}创建 .venv ...${NC}"
        "${py}" -m venv "${ROOT_DIR}/.venv"
    fi
    local vpy="${ROOT_DIR}/.venv/bin/python"
    local spec
    spec="$(python_spec)"
    echo -e "   ${CYAN}pip install -e ${spec} ...${NC}"
    "${vpy}" -m pip install --upgrade pip
    "${vpy}" -m pip install -e "${spec}"
    if [ "${WITH_PLAYWRIGHT}" = true ] || [ "${WITH_ALL_PYTHON}" = true ]; then
        "${vpy}" -m playwright install chromium || true
    fi
}

init_dotenv() {
    if [ -f "${ROOT_DIR}/.env" ]; then
        echo -e "   ${GREEN}✓ .env 已存在${NC}"
        return
    fi
    if [ -f "${ROOT_DIR}/.env.example" ]; then
        cp "${ROOT_DIR}/.env.example" "${ROOT_DIR}/.env"
        echo -e "   ${GREEN}✓ 已从 .env.example 生成 .env${NC}"
    fi
}

init_platform_data() {
    if [ -f "${ROOT_DIR}/data/autopilot_platform.db" ]; then
        echo -e "   ${GREEN}✓ 已有 data/ 主库，跳过 init${NC}"
        return
    fi
    local vpy="${ROOT_DIR}/.venv/bin/python"
    if [ ! -x "${vpy}" ]; then
        echo -e "   ${YELLOW}⚠ 无 .venv，跳过 init_platform.py${NC}"
        return
    fi
    echo -e "   ${CYAN}tools/init_platform.py init ...${NC}"
    "${vpy}" "${ROOT_DIR}/tools/init_platform.py" init
}

show_resources() {
    echo -e "\n${BOLD}1. 内置设备资源（本仓库 resources/ 已有则跳过）${NC}"
    local items=(
        "re_adb (platform-tools zip)|re_adb/$(adb_zip_name)"
        "re_aapt|re_aapt/$(aapt_zip_name)"
        "re_scrcpy/scrcpy-server.jar|re_scrcpy/scrcpy-server.jar"
        "re_uiautomator 设备侧 apk|re_uiautomator/app-uiautomator.apk"
        "re_go_ios/executable|$(go_ios_bin)"
        "re_go_ios/devimages|re_go_ios/devimages"
    )
    local item name rel
    for item in "${items[@]}"; do
        name="${item%%|*}"
        rel="${item#*|}"
        if local_resource "${rel}"; then
            echo -e "   ${GREEN}[SKIP]${NC} ${name} 已在 resources/，不重复下载"
        else
            echo -e "   ${YELLOW}[MISS]${NC} ${name} 未找到"
        fi
    done
}

show_summary() {
    echo -e "\n${BOLD}就绪摘要${NC}"
    local t
    for t in adb java node npm appium; do
        if has_cmd "${t}"; then
            echo -e "   ${GREEN}✔ ${t}${NC} ${DIM}-> $(command -v "${t}")${NC}"
        else
            echo -e "   ${YELLOW}○ ${t}${NC} 不在 PATH"
        fi
    done
    if [ -x "${ROOT_DIR}/.venv/bin/python" ]; then
        echo -e "   ${GREEN}✔ Python venv${NC}"
    else
        echo -e "   ${YELLOW}○ .venv 未创建${NC}"
    fi
    if [ -d "${ROOT_DIR}/autopilot_platform/frontend/node_modules" ]; then
        echo -e "   ${GREEN}✔ frontend node_modules${NC}"
    else
        echo -e "   ${YELLOW}○ frontend 尚未 npm install${NC}"
    fi
}

normalize_path

echo -e "${BOLD}${CYAN}======================================================${NC}"
echo -e "${BOLD}${CYAN}   AutoPilot Platform 新设备一键安装 (${OS_TYPE})${NC}"
echo -e "${BOLD}${CYAN}======================================================${NC}"
echo -e "   仓库: ${DIM}${ROOT_DIR}${NC}"
echo -e "   resources: ${DIM}${LOCAL_RES}${NC}"

show_resources

if [ "${CHECK_ONLY}" = true ]; then
    echo -e "\n${CYAN}[--check] 仅体检，不安装${NC}"
    show_summary
    exit 0
fi

echo -e "\n${BOLD}2. Android 设备层 adb${NC}"
if local_resource "re_adb/$(adb_zip_name)"; then
    echo -e "   ${GREEN}[SKIP] 使用仓库 resources/re_adb${NC}"
elif has_cmd adb; then
    echo -e "   ${GREEN}✓ PATH 上已有 adb${NC}"
else
    install_portable_adb || true
fi
echo -e "\n${BOLD}3. JDK 17+${NC}"
install_jdk || true

echo -e "\n${BOLD}4. Node.js${NC}"
ensure_node || true
if [ "${SKIP_APPIUM}" = true ]; then
    echo -e "   ${YELLOW}[SKIP] 按参数跳过 Appium${NC}"
else
    install_appium_stack || true
fi

echo -e "\n${BOLD}5. 环境文件 .env${NC}"
init_dotenv

if [ "${SKIP_PYTHON}" = true ]; then
    echo -e "\n${BOLD}6. [SKIP] Python 依赖${NC}"
else
    echo -e "\n${BOLD}6. Python 虚拟环境与项目依赖${NC}"
    install_python_env || true
fi

if [ "${SKIP_FRONTEND}" = true ]; then
    echo -e "\n${BOLD}7. [SKIP] 按参数跳过前端 npm install${NC}"
else
    echo -e "\n${BOLD}7. 前端 npm install${NC}"
    install_frontend || true
fi

if [ "${SKIP_INIT}" = true ]; then
    echo -e "\n${BOLD}8. [SKIP] 按参数跳过 init_platform${NC}"
else
    echo -e "\n${BOLD}8. 初始化 data/${NC}"
    init_platform_data || true
fi

if has_cmd adb; then
    (unset ADB_SERVER_SOCKET; adb start-server >/dev/null 2>&1 || true)
fi

show_summary

echo -e "\n${BOLD}${CYAN}======================================================${NC}"
echo -e "${BOLD}${GREEN}   安装流程结束。建议再跑预检：${NC}"
echo -e "     ${CYAN}.venv/bin/python tools/preflight.py${NC}"
echo -e "   启动 Platform+Web：  ${CYAN}.venv/bin/python start_dev.py${NC}"
echo -e "   启动 Runner：  ${CYAN}python -m autopilot_platform.runner --server http://127.0.0.1:8000 --token-env MC_RUNNER_TOKEN${NC}"
echo -e "${BOLD}${CYAN}======================================================${NC}"
