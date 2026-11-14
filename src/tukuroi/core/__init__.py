# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
The engine of Fixit, built on ``ast`` and ``tokenize`` (#21): it parses the
source, runs the rules, applies their fixes, and formats with ruff.
"""
