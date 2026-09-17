"""Independent Clang configure for the unchanged 2009 GNU release."""
from security.historical.v2_configure import configure
from security.historical.v2_study import write


if __name__ == "__main__":
    row = configure("coreutils-8.4", directory_name="coreutils-8.4-clang", compiler="clang-21 -std=gnu99",
                    extra_options=("CPPFLAGS=-D_IO_ftrylockfile=1 -D_IO_IN_BACKUP=0x100",))
    row["reconstruction_rationale"] = "Both GCC C17 and C99 attempts fail because modern glibc removed gets while historical gnulib's GCC warning-only declaration assumes it exists. Run the release's own Clang feature checks and compiler-conditional warning machinery in an independent build directory. No fake gets declaration or release-source/header edits. This is build-compiler configuration, not pointer-analysis tuning."
    write("v2_coreutils_8_4_clang_configuration.json", row)
