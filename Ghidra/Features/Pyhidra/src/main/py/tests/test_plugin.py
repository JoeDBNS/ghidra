import abc
import functools
import importlib.metadata
from pathlib import Path
import typing

import jpype
import pyhidra
import pytest


# mark this entire module
pytestmark = pytest.mark.plugin


SETUP_KEY = "pyhidra.setup"
PRE_LAUNCH_KEY = "pyhidra.pre_launch"
NAME_KEY = "names"


plugin_registry: typing.Dict[str, typing.List["EntryPoint"]] = {
   SETUP_KEY: [],
   PRE_LAUNCH_KEY: [],
   NAME_KEY: []
}


class PluginTest:
    
    ran_setup = False
    ran_prelaunch = False
    
    details: pyhidra.ExtensionDetails = None
    
    def __init_subclass__(cls) -> None:
        cls.details = pyhidra.ExtensionDetails(
            name=cls.__name__,
            description="Test Plugin",
            author=""
        )

        _setup = cls.setup
        _prelaunch = cls.prelaunch
        
        @functools.wraps(_setup)
        def setup(launcher: pyhidra.HeadlessPyhidraLauncher):
            _setup(launcher)
            cls.ran_setup = True

        @functools.wraps(_prelaunch)
        def prelaunch():
            _prelaunch()
            cls.ran_prelaunch = True
        
        cls.setup = setup
        cls.prelaunch = prelaunch
        
        name = cls.__name__
        plugin_registry[SETUP_KEY].append(EntryPoint(name, cls.setup))
        plugin_registry[PRE_LAUNCH_KEY].append(EntryPoint(name, cls.prelaunch))
        plugin_registry[NAME_KEY].append(name)
    
    @classmethod
    @abc.abstractmethod
    def setup(cls, launcher: pyhidra.HeadlessPyhidraLauncher):
        ...
    
    @classmethod
    @abc.abstractmethod
    def prelaunch(cls):
        ...

    @classmethod
    def test_setup(cls):
        assert cls.ran_setup

    @classmethod
    def test_prelaunch(cls):
        assert cls.ran_prelaunch


class EntryPoint:

    def __init__(self, name, callback):
        self.name = name
        self.callback = callback

    def load(self):
        return self.callback


def _monkey_patch_entry_points():
    # hardcode the entry points so we don't need to pip install anything
    backup = importlib.metadata.entry_points

    def entry_points(*args, **kwargs):
        group = kwargs.get("group")
        if group in plugin_registry:
            return plugin_registry[group]
        return backup(*args, **kwargs)

    importlib.metadata.entry_points = entry_points


@pytest.fixture(scope="module", autouse=True)
def with_ghidra():
    """
    Automatically used fixture that starts Ghidra,
    yields nothing and then cleans up the test plugins
    """
    _monkey_patch_entry_points()
    try:
        launcher = pyhidra.HeadlessPyhidraLauncher()
        launcher.start()
        yield # can't yield None
    finally:
        # we need to close the GhidraClassLoader so we can delete the extension
        from java.lang import ClassLoader
        ClassLoader.getSystemClassLoader().close()
        jpype.shutdownJVM()
        for plugin in plugin_registry["names"]:
            try:
                launcher.uninstall_plugin(plugin)
            except Exception:
                pass


class TestValidPlugin(PluginTest):
    
    @classmethod
    def setup(cls, launcher: pyhidra.HeadlessPyhidraLauncher):
        source_path = Path(__file__).parent / "data" / "good_plugin"
        launcher.install_plugin(source_path, cls.details)
    
    @classmethod
    def prelaunch(cls):
        DummyTestRecognizer = jpype.JClass("ghidra.pyhidra.test.DummyTestRecognizer")
        DummyTestRecognizer.preLaunchInitialized = True
    
    @classmethod
    def test_extension_point(cls):
        from ghidra.app.util.recognizer import Recognizer
        from ghidra.util.classfinder import ClassSearcher
        DummyTestRecognizer = jpype.JClass("ghidra.pyhidra.test.DummyTestRecognizer")
        assert DummyTestRecognizer in ClassSearcher.getClasses(Recognizer)


class TestBadPlugin(PluginTest):
    
    launcher: pyhidra.HeadlessPyhidraLauncher = None
    
    @classmethod
    def setup(cls, launcher: pyhidra.HeadlessPyhidraLauncher):
        source_path = Path(__file__).parent / "data" / "bad_plugin"
        launcher.install_plugin(source_path, cls.details)
        cls.launcher = launcher
    
    @classmethod
    def prelaunch(cls):
        pass
    
    @classmethod
    def test_no_plugin(cls):
        # ensures there is no plugin
        assert cls.launcher
        extension_path = cls.launcher.extension_path
        assert not (extension_path / cls.__name__).exists()
