{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };
  outputs = {
    nixpkgs,
    flake-utils,
    ...
  }:
  flake-utils.lib.eachDefaultSystem (system:
    let
      pkgs = nixpkgs.legacyPackages.${system};
      lib = pkgs.lib;
      python = pkgs.python313;
      pyPkgs = python.pkgs // rec {
        ttkbootstrap-icons = pyPkgs.buildPythonPackage  {
          pname = "ttkbootstrap-icons";
          version = "v4.0.0";
          src = pkgs.fetchurl {
            url = "https://files.pythonhosted.org/packages/b0/7e/f610e3d08fc64c419ff6a0c6d0b168e0fe15ad181f45f51ef37ea3f434b7/ttkbootstrap_icons-4.0.0-py3-none-any.whl";
            sha256 = "75ac2a2205be559a348bc6df037976f02e9a0cf4058e3ed037ddf2520dfa8cfd";
          };
          format = "wheel";
          doCheck = false;
          propagatedBuildInputs = with pyPkgs; [
            pillow
            typing-extensions
          ];
        };
        ttkbootstrap-icons-bs = pyPkgs.buildPythonPackage {
          pname = "ttkbootstrap-icons-bs";
          version = "v1.0.0";
          src = pkgs.fetchurl {
            url = "https://files.pythonhosted.org/packages/cb/9a/65c1178b581f952fbb269a5f9af23b82df5adf90e2a3dc804634dd0e9414/ttkbootstrap_icons_bs-1.0.0-py3-none-any.whl";
            sha256 = "22fe913f94cf007cd8d26a5889e9d438569d8d0d3b0e6983017fb5ce6dc42d67";
          };
          format = "wheel";
          doCheck = false;
          propagatedBuildInputs = with pyPkgs; [
            ttkbootstrap-icons
          ];
        };
      };
      pyproject = fromTOML (builtins.readFile ./pyproject.toml);
      project = pyproject.project;
      fixString = x: lib.strings.toLower (builtins.replaceStrings ["_"] ["-"] x);
      getPkgs = x: lib.attrsets.attrVals (map fixString x) pyPkgs;
      package = pyPkgs.buildPythonPackage {
        pname = project.name;
        version = project.version;
        format = "pyproject";
        src = ./.;
        build-system = getPkgs pyproject.build-system.requires;
        dependencies = getPkgs project.dependencies ++ [
          pyPkgs.tkinter
          pkgs.ffmpeg-full
        ];
      };
      editablePackage = pyPkgs.mkPythonEditablePackage {
        pname = project.name;
        version = project.version;
        scripts = project.scripts;
        root = "$PWD/src";
        dependencies = package.build-system ++ getPkgs project.optional-dependencies.dev;
      };
    in
    {
      packages.default = pyPkgs.toPythonApplication package;
      devShells.default = pkgs.mkShell {
        inputsFrom = [
          package
        ];
        buildInputs = [
          editablePackage
          pyPkgs.build
        ];
      };
    }
  );
}
