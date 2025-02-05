"""
Copyright 2017 BlazeMeter Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
import os
from abc import abstractmethod

from bzt import TaurusConfigError
from bzt.modules import SubprocessedExecutor
from bzt.utils import TclLibrary, RequiredTool, Node, CALL_PROBLEMS, RESOURCES_DIR
from bzt.utils import get_full_path, is_windows, to_json, dehumanize_time, iteritems


class JavaScriptExecutor(SubprocessedExecutor):
    def __init__(self):
        super(JavaScriptExecutor, self).__init__()
        self.tools_dir = None
        self.node = None
        self.npm = None

    def prepare(self):
        super(JavaScriptExecutor, self).prepare()
        self.tools_dir = get_full_path(self.settings.get("tools-dir", self.tools_dir))
        self.env.add_path({"NODE_PATH": os.path.join(self.tools_dir, "node_modules")})

    @abstractmethod
    def get_launch_cmdline(self, *args):
        pass

    @abstractmethod
    def get_launch_cwd(self, *args):
        pass


class MochaTester(JavaScriptExecutor):
    """
    Mocha tests runner

    :type mocha: Mocha
    :type mocha_plugin: TaurusMochaPlugin
    """

    def __init__(self):
        super(MochaTester, self).__init__()
        self.tools_dir = "~/.bzt/selenium-taurus/mocha"
        self.mocha = None
        self.mocha_plugin = None

    def prepare(self):
        super(MochaTester, self).prepare()
        self.env.add_path({"NODE_PATH": "node_modules"}, finish=True)
        self.script = self.get_script_path()
        if not self.script:
            raise TaurusConfigError("Script not passed to runner %s" % self)

        self.install_required_tools()
        self.reporting_setup(suffix='.ldjson')

    def install_required_tools(self):
        tcl_lib = self._get_tool(TclLibrary)
        self.node = self._get_tool(Node)
        self.npm = self._get_tool(NPM)
        self.mocha = self._get_tool(Mocha, tools_dir=self.tools_dir, node_tool=self.node, npm_tool=self.npm)
        self.mocha_plugin = self._get_tool(TaurusMochaPlugin)

        web_driver = self._get_tool(
            JSSeleniumWebdriver, tools_dir=self.tools_dir, node_tool=self.node, npm_tool=self.npm)

        tools = [tcl_lib, self.node, self.npm, self.mocha, self.mocha_plugin, web_driver]
        self._check_tools(tools)

    def get_launch_cmdline(self, *args):
        return [self.node.tool_path, self.mocha_plugin.tool_path] + list(args)

    def startup(self):
        mocha_cmdline = self.get_launch_cmdline(
            "--report-file",
            self.report_file,
            "--test-suite",
            self.script
        )
        load = self.get_load()
        if load.iterations:
            mocha_cmdline += ['--iterations', str(load.iterations)]

        if load.hold:
            mocha_cmdline += ['--hold-for', str(load.hold)]

        self.process = self._execute(mocha_cmdline, cwd=self.get_launch_cwd())


class WebdriverIOExecutor(JavaScriptExecutor):
    """
    WebdriverIO-based test runner

    :type wdio: WDIO
    :type wdio_taurus_plugin: TaurusWDIOPlugin
    """

    def __init__(self):
        super(WebdriverIOExecutor, self).__init__()
        self.tools_dir = "~/.bzt/selenium-taurus/wdio-mjs"
        self.wdio = None
        self.wdio_taurus_plugin = None

    def prepare(self):
        super(WebdriverIOExecutor, self).prepare()
        self.env.add_path({"NODE_PATH": "node_modules"}, finish=True)
        # NODE_PATH doesn't work for ems modules -> we will change pwd so executor sees tools node_modules...
        self.script = self.get_script_path()
        if not self.script:
            raise TaurusConfigError("Script not passed to executor %s" % self)

        self.tools_dir = get_full_path(self.settings.get("tools-dir", self.tools_dir))
        self.install_required_tools()
        self.reporting_setup(suffix='.ldjson')

    def install_required_tools(self):
        tcl_lib = self._get_tool(TclLibrary)
        self.node = self._get_tool(Node)
        self.npm = self._get_tool(NPM)
        self.wdio = self._get_tool(WDIO, tools_dir=self.tools_dir, node_tool=self.node, npm_tool=self.npm)
        self.wdio_reporter = self._get_tool(WDIOReporter, tools_dir=self.tools_dir, node_tool=self.node, npm_tool=self.npm)
        self.wdio_runner = self._get_tool(WDIORunner, tools_dir=self.tools_dir, node_tool=self.node, npm_tool=self.npm)
        self.wdio_taurus_plugin = self._get_tool(TaurusWDIOPlugin, tools_dir=self.tools_dir, node_tool=self.node, npm_tool=self.npm)
        self.node_tsx_module = self._get_tool(NodeTSXModule, tools_dir=self.tools_dir, node_tool=self.node, npm_tool=self.npm)

        wdio_mocha_plugin = self._get_tool(
            WDIOMochaPlugin, tools_dir=self.tools_dir, node_tool=self.node, npm_tool=self.npm)

        tools = [tcl_lib, self.node, self.npm, self.wdio, self.wdio_taurus_plugin, self.wdio_reporter, self.wdio_runner, wdio_mocha_plugin, self.node_tsx_module]

        self._check_tools(tools)

    def get_launch_cmdline(self, *args):
        return [self.node.tool_path, '@taurus/wdio-taurus-plugin'] + list(args)

    def get_launch_cwd(self, *args):
        return self.tools_dir + "/node_modules"

    def startup(self):
        script_dir = get_full_path(self.script, step_up=1)
        script_file = os.path.basename(self.script)
        cmdline = self.get_launch_cmdline(
            "--report-file",
            self.report_file,
            "--wdio-config",
            script_file,
        )

        load = self.get_load()
        if load.iterations:
            cmdline += ['--iterations', str(load.iterations)]

        if load.hold:
            cmdline += ['--hold-for', str(load.hold)]

        cmdline += ['--cwd', script_dir]

        self.process = self._execute(cmdline, cwd=self.get_launch_cwd())


class NPM(RequiredTool):
    def __init__(self, **kwargs):
        super(NPM, self).__init__(installable=False, **kwargs)

    def check_if_installed(self):
        candidates = ["npm"]
        if is_windows():
            candidates.append("npm.cmd")
        for candidate in candidates:
            self.log.debug("Trying '%r' as NPM Tool...", candidate)
            try:
                out, err = self.call([candidate, '--version'])
            except CALL_PROBLEMS as exc:
                self.log.debug("%r is not installed: %s", candidate, exc)
                continue

            if err:
                out += err
            self.log.debug("%s output: %s", candidate, out)
            self.tool_path = candidate
            return True

        return False


class NPMPackage(RequiredTool):
    PACKAGE_NAME = ""

    def __init__(self, tools_dir, node_tool, npm_tool, **kwargs):
        super(NPMPackage, self).__init__(**kwargs)
        self.package_name = self.PACKAGE_NAME
        self.is_module_package = False
        if self.package_name.startswith("@"):
            package_name_split = self.package_name.split("@")
            self.package_name = '@{}'.format(package_name_split[1])
            if len(package_name_split) > 2:
                self.version = package_name_split[2]
        elif "@" in self.package_name:
            self.package_name, self.version = self.package_name.split("@")

        self.tools_dir = tools_dir
        self.node = node_tool
        self.npm = npm_tool

    def check_if_installed(self):
        ok_msg = "%s is installed" % self.package_name

        # NODE_PATH doesn't work for ems modules - look if symlink/node_modules are present,
        # if not, change dir to tool node_modules
        process_cwd = None
        if not self.is_module_package:
            cmdline = [self.node.tool_path, "-e",
                       "require('%s'); console.log('%s');" % (self.package_name, ok_msg)]
            self.log.debug("NODE_PATH for check: %s", self.env.get("NODE_PATH"))
        else:
            cmdline = [ self.node.tool_path, "--input-type=module", "-e",
                        "import('%s').then(() => { console.log('%s'); process.exit(0); }).catch(() => process.exit(1));" % (self.package_name, ok_msg)]
            if not os.path.exists("./node_modules"):
                process_cwd = os.path.join(self.tools_dir, "node_modules")
            self.log.debug("cwd for check: %s", "." if process_cwd is None else process_cwd)

        self.log.debug("%s check cmdline: %s", self.package_name, cmdline)

        try:
            out, _ = self.call(cmdline, cwd=process_cwd)
            return ok_msg in out
        except CALL_PROBLEMS as exc:
            self.log.debug("%s check failed: %s", self.package_name, exc)
            return False

    def install(self):
        package_name = self.package_name
        if self.version:
            package_name += "@" + self.version
        cmdline = [self.npm.tool_path, 'install', package_name, '--prefix', self.tools_dir]

        try:
            out, err = self.call(cmdline)
        except CALL_PROBLEMS as exc:
            self.log.debug("%s install failed: %s", self.package_name, exc)
            return

        self.log.debug("%s install stdout: %s", self.tool_name, out)
        if err:
            self.log.warning("%s install stderr: %s", self.tool_name, err)

class NPMModulePackage(NPMPackage):
    def __init__(self, tools_dir, node_tool, npm_tool, **kwargs):
        super(NPMModulePackage, self).__init__(tools_dir, node_tool, npm_tool, **kwargs)
        self.is_module_package = True


class NPMLocalModulePackage(NPMPackage):
    PACKAGE_LOCAL_PATH = ""
    def __init__(self, tools_dir, node_tool, npm_tool, **kwargs):
        super(NPMLocalModulePackage, self).__init__(tools_dir, node_tool, npm_tool, **kwargs)

        self.is_module_package = True
        self.package_local_path = self.PACKAGE_LOCAL_PATH
        if not os.path.isabs(self.package_local_path):
            self.package_local_path = os.path.normpath(os.path.join(RESOURCES_DIR, self.package_local_path))

    def install(self):
        cmdline = [self.npm.tool_path, 'install', ".", '--install-links', '--prefix', self.tools_dir]

        try:
            out, err = self.call(cmdline, cwd=self.package_local_path)
        except CALL_PROBLEMS as exc:
            self.log.debug("%s install failed: %s", self.package_name, exc)
            return

        self.log.debug("%s install stdout: %s", self.tool_name, out)
        if err:
            self.log.warning("%s install stderr: %s", self.tool_name, err)


class Mocha(NPMPackage):
    PACKAGE_NAME = "mocha@10.6.0"


class JSSeleniumWebdriver(NPMPackage):
    PACKAGE_NAME = "selenium-webdriver@4.23.0"

class WDIO(NPMModulePackage):
    PACKAGE_NAME = "@wdio/cli@9.2.1"

class WDIORunner(NPMModulePackage):
    PACKAGE_NAME = "@wdio/local-runner@9.2.1"

class WDIOReporter(NPMModulePackage):
    PACKAGE_NAME = "@wdio/reporter@9.1.3"

class WDIOMochaPlugin(NPMModulePackage):
    PACKAGE_NAME = "@wdio/mocha-framework@9.1.3"

class NodeTSXModule(NPMModulePackage):
    PACKAGE_NAME = "tsx@4.19.2"

class TaurusWDIOPlugin(NPMLocalModulePackage):
    PACKAGE_NAME = "@taurus/wdio-taurus-plugin@1.0.0"
    PACKAGE_LOCAL_PATH = "./wdio-taurus-plugin"

class TaurusMochaPlugin(RequiredTool):
    def __init__(self, **kwargs):
        tool_path = os.path.join(RESOURCES_DIR, "mocha-taurus-plugin.js")
        super(TaurusMochaPlugin, self).__init__(tool_path=tool_path, installable=False, **kwargs)

class TaurusNewmanPlugin(RequiredTool):
    def __init__(self, **kwargs):
        tool_path = os.path.join(RESOURCES_DIR, "newman-reporter-taurus.js")
        super(TaurusNewmanPlugin, self).__init__(tool_path=tool_path, installable=False, **kwargs)
