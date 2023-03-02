# SPDX-License-Identifier: BSD-3-Clause

from abc           import abstractmethod
from typing        import Dict, Union, Optional, List, Tuple
from pathlib       import Path

from ...build.plat import TemplatedPlatform
from ...build.run  import BuildPlan
from ...hdl.ir     import Fragment

__all__ = (
	'OpenLANEPlatform',
)

class OpenLANEPlatform(TemplatedPlatform):
	'''
	.. note::

		See https://github.com/The-OpenROAD-Project/OpenLane#setting-up-openlane for instructions on
		setting up OpenLANE and the various PDKs.

	.. note::

		See https://openlane.readthedocs.io/en/latest/configuration/README.html#variables-information for
		more detailed information on the various ``flow_settings`` available.

	Required tools:
		* ``OpenLANE``
		* ``docker``

	Build products:
		* ``config.tcl``: OpenLANE Flow configuration
		* ``{{name}}.sdc``: Timing and clock constraints
		* ``{{name}}.v``: Design Verilog
		* ``{{name}}.debug.v``: Design debug verilog
		* ``runs/*``: OpenLANE flow output

	'''

	openlane_root : Optional[Path] = None
	pdk_root      : Optional[Path] = None
	toolchain = 'openlane'

	@property
	@abstractmethod
	def pdk(self) -> str:
		raise NotImplementedError('Platform must implement this property')

	@property
	@abstractmethod
	def cell_library(self) -> str:
		raise NotImplementedError('Platform must implement this property')

	@property
	@abstractmethod
	def flow_settings(self) -> Dict[str, Union[str, int, float]]:
		raise NotImplementedError('Platform must implement this property')

	_openlane_required_tools = (
		'docker',
	)

	_openlane_file_templates = {
		'build_{{name}}.sh': '''
			# {{autogenerated}}
			set -e{{verbose("x")}}
			[ -n "${{platform._toolchain_env_var}}" ] && . "${{platform._toolchain_env_var}}"
			{{emit_commands("sh")}}
		''',
		'''{{name}}.v''': r'''
			/* {{autogenerated}} */
			{{emit_verilog()}}
		''',
		'''{{name}}.debug.v''': r'''
			/* {{autogenerated}} */
			{{emit_debug_verilog()}}
		''',
		'''config.tcl''': r'''
		# {{autogenerated}}
		# Design Information
		set ::env(DESIGN_NAME) "{{name}}"
		set ::env(VERILOG_FILES) "/design_{{name}}/{{name}}.v"
		set ::env(SDC_FILE) "/design_{{name}}/{{name}}.sdc"
		{% if platform.default_clk %}
		# Clocking Settings
		# TODO: Get rid of magic number `1e-9`
		set ::env(CLOCK_PERIOD) "{{platform.default_clk_constraint.period / 1e-9}}"
		set ::env(CLOCK_PORT) "{{platform._default_clk_name}}"
		set ::env(CLOCK_NET) $::env(CLOCK_PORT)
		{% else %}
		# No Clock
		set ::env(CLOCK_TREE_SYNTH) 0
		set ::env(CLOCK_PORT) ""
		{% endif %}
		# PDK Settings
		set ::env(PDK) "{{platform.pdk}}"
		set ::env(STD_CELL_LIBRARY) "{{platform.cell_library}}"
		# Design "{{name}}" Specific flow settings
		{% for e, v in platform.flow_settings.items() %}
		set ::env({{e}}) {{v}}
		{% endfor %}
		# Pull in {{platform.pdk}} settings
		set pdk_config $::env(DESIGN_DIR)/$::env(PDK)_$::env(STD_CELL_LIBRARY)_config.tcl
		if { [file exists $pdk_config] == 1 } {
			source $pdk_config
		}
		''',
		'''{{name}}.sdc''': r'''
		# {{autogenerated}}
		{% for net_sig, port_sig, frq in platform.iter_clock_constraints() -%}
			{% if port_sig is not None -%}
				create_clock -name {{port_sig.name|tcl_escape}} -period {{ 1e-9 / frq }} [get_ports {{port_sig.name|tcl_escape}}]
			{% else -%}
				create_clock -name {{net_sig.name|tcl_escape}} -period {{ 1e-9 / frq }} [get_nets {{net_sig.name|hierarchy("/")|tcl_escape}}]
			{% endif -%}
		{% endfor %}
		# {{get_override("add_constraints")|default("# (add_constraints placeholder)")}}
		'''
	}

	_openlane_command_templates = (
		r'''
		{{invoke_tool("docker")}}
			run
			{% if get_override_flag("openlane_interactive") %}
			-it
			{% endif %}
			{% if not get_override_flag("docker_networked") %}
			--network none
			{% endif %}
			--rm
			--name "torii-openlane-{{name}}"
			-v {{get_override("OPENLANE_ROOT")|default(platform.openlane_root)}}:/openLANE_flow
			-v {{get_override("PDK_ROOT")|default(platform.pdk_root)}}:/PDK
			-v {{platform._build_dir}}:/design_{{name}}
			-e PDK_ROOT=/PDK
			-u $(id -u):$(id -g)
			efabless/openlane:{{get_override("OPENLANE_TAG")|default("latest")}}
			sh -c "./flow.tcl {{verbose("-verbose 2")}} -design /design_{{name}} -config_file /design_{{name}}/config.tcl"
		''',
	)

	_build_dir : Optional[Path] = None

	def __init__(self) -> None:
		super().__init__()

	@property
	def required_tools(self) -> Tuple[str]:
		return self._openlane_required_tools

	@property
	def file_templates(self) -> Dict[str, str]:
		return self._openlane_file_templates

	@property
	def command_templates(self) -> List[str]:
		return self._openlane_command_templates

	def build(self, *args, **kwargs):
		self._build_dir = Path(kwargs.get('build_dir', 'build')).resolve()
		return super().build(*args, **kwargs)

	def toolchain_prepare(self, fragment: Fragment, name: str, **kwargs) -> BuildPlan:

		# Propagate module ports for io placement
		a_ports = kwargs.get('ports', None)
		if a_ports is not None:
			fragment._propagate_ports(ports = a_ports, all_undef_as_ports = False)

		return super().toolchain_prepare(fragment, name, **kwargs)
