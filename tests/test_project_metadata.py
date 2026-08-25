from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_required_community_files_are_present() -> None:
    required_files = (
        "LICENSE",
        "README.md",
        "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md",
        "SECURITY.md",
        "SUPPORT.md",
        ".github/pull_request_template.md",
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/feature_request.yml",
    )

    for relative_path in required_files:
        path = PROJECT_ROOT / relative_path
        assert path.is_file(), f"Missing required community file: {relative_path}"
        assert path.read_text(encoding="utf-8").strip(), (
            f"Required community file is empty: {relative_path}"
        )


def test_license_file_contains_complete_apache_2_terms() -> None:
    license_text = (PROJECT_ROOT / "LICENSE").read_text(encoding="utf-8")

    assert "Apache License" in license_text
    assert "Version 2.0, January 2004" in license_text
    assert "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION" in license_text
    for section in range(1, 10):
        assert f"   {section}." in license_text
    assert "END OF TERMS AND CONDITIONS" in license_text


def test_package_metadata_uses_apache_2_spdx_expression() -> None:
    metadata = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'license = "Apache-2.0"' in metadata
    assert 'license-files = ["LICENSE"]' in metadata
    assert "LicenseRef-Proprietary" not in metadata


def test_public_project_guidance_matches_apache_2() -> None:
    for relative_path in ("README.md", "CONTRIBUTING.md", "SECURITY.md", "docs/releasing.md"):
        content = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        assert "Apache" in content
        assert "proprietary license" not in content.lower()
