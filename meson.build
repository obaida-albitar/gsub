project(
  'gsub',
  version: '0.2.0',
  license: 'GPL-3.0-or-later',
  meson_version: '>= 0.63.0',
  default_options: [
    'warning_level=1',
  ],
)

# --- Dependencies / pkg-config ----------------------------------------------
dependency('libadwaita-1', version: '>= 1.8')
dependency('gtk4', version: '>= 4.14')
dependency('glib-2.0')

gnome = import('gnome')

# --- Python -----------------------------------------------------------------
python = import('python').find_installation('python3')
python_dir = python.get_install_dir()

pkgdatadir = get_option('datadir') / 'gsub'

# --- blueprint-compiler -----------------------------------------------------
# blueprint-compiler is required to compile the .blp templates. It is normally
# provided by the distribution (e.g. `blueprint-compiler` on Fedora/Debian); on
# systems that vendor it as a meson subproject wrap, add the wrap file under
# subprojects/ and this find_program will pick it up automatically.
blueprint_compiler = find_program('blueprint-compiler', required: true)

# --- Compile .blp -> .ui ----------------------------------------------------
# Each template's .ui is produced by compiling its .blp. The generated .ui files
# become inputs to the gresource (sourced from the build directory).
blueprints_dir = meson.current_source_dir() / 'data' / 'blueprints'

blueprint_names = [
  'window',
  'home-screen',
  'batch-confirm-dialog',
  'batch-operations-panel',
  'batch-file-row',
  'time-shift',
  'bulk-apply-style',
  'track-selection',
  'ass-info-styles',
  'video-player',
  'editor-panel',
  'subtitle-list-row',
  'subtitle-list',
  'batch-file-list',
]

compiled_ui = []
foreach name : blueprint_names
  ui = custom_target(
    name + '.ui',
    input: blueprints_dir / (name + '.blp'),
    output: name + '.ui',
    command: [blueprint_compiler, 'compile', '--output', '@OUTPUT@', '@INPUT@'],
  )
  compiled_ui += ui
endforeach

# --- gresource --------------------------------------------------------------
# For a Python project we cannot use gnome.compile_resources (it emits C source
# requiring a C compiler). Instead we invoke glib-compile-resources directly to
# produce a binary app.gsub.gresource blob from the manifest + compiled .ui files.
glib_compile_resources = find_program('glib-compile-resources')
gresource_xml = meson.current_source_dir() / 'data' / 'app.gsub.gresource.xml'

gresource = custom_target(
  'app.gsub.gresource',
  input: gresource_xml,
  output: 'app.gsub.gresource',
  command: [
    glib_compile_resources,
    '--target', '@OUTPUT@',
    '--sourcedir', meson.current_build_dir(),   # finds the compiled .ui files
    '--sourcedir', meson.current_source_dir() / 'data',  # finds style.css + svg
    '@INPUT@',
  ],
  depends: compiled_ui,
  install: true,
  install_dir: pkgdatadir,
)

# --- Application icon & desktop file ----------------------------------------
icon_dir = get_option('datadir') / 'icons' / 'hicolor' / 'scalable' / 'apps'
install_data('data' / 'app.gsub.svg', install_dir: icon_dir, rename: 'app.gsub.svg')

desktop_dir = get_option('datadir') / 'applications'
install_data('data' / 'app.gsub.desktop', install_dir: desktop_dir)

# --- Python package ---------------------------------------------------------
# Install the whole subtitle_editor package into the system/venv site-packages.
fs = import('fs')

# Enumerate every .py in the package so the install set is explicit and
# __pycache__ artifacts are never picked up.
package_files = run_command(
  python,
  ['-c', 'import os,sys; r="subtitle_editor"; out=[];\n'
          + '[out.append(os.path.relpath(os.path.join(d,f), r)) for d,_,fs in os.walk(r) for f in fs if f.endswith(".py")]\n'
          + 'print("\\n".join(out))'],
  check: true,
).stdout().strip().split('\n')

foreach src : package_files
  install_data(
    meson.current_source_dir() / 'subtitle_editor' / src,
    install_dir: python_dir / 'subtitle_editor' / fs.parent(src),
    rename: fs.name(src),
  )
endforeach

# --- Post-install -----------------------------------------------------------
# Refresh icon and desktop caches after install.
gnome.post_install(
  glib_compile_schemas: true,
  gtk_update_icon_cache: true,
  update_desktop_database: true,
)

# --- Tests ------------------------------------------------------------------
test('pytest',
  python,
  args: ['-m', 'pytest', meson.current_source_dir() / 'tests'],
  workdir: meson.current_source_dir(),
  env: {'PYTHONPATH': meson.current_source_dir()},
)
