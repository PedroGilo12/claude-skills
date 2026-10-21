# Template for a Zephyr unit test project (native_sim board).
# Replace <MODULE> with the module name and adjust the paths relative to the .c under test.
#
# Rules:
#  - Link THE .c UNDER TEST here (so gcov measures the real unit), besides the suite.
#  - The fakes (FFF) are defined inside the suite itself; they only need a separate .c
#    if they are shared between suites.
#  - target_include_directories must reach the module's .h and its project headers.
#
# Run (from the twister working dir), then write the test report:
#   west twister --coverage -p native_sim/native/64 -T <suite_path> --coverage-basedir <module_root>
#   python3 <suite_path>/test_report.py twister-out/tests.html $(find twister-out -name handler.log)

cmake_minimum_required(VERSION 3.20.0)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(test_<MODULE>)

target_sources(app PRIVATE
    src/test_<MODULE>.c
    # .c under test — adjust the relative path:
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../<path>/<MODULE>.c
)

target_include_directories(app PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../<path>
)
