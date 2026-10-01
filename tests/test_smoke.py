# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
import jtalm


def test_package_imports() -> None:
    assert jtalm.__name__ == "jtalm"
