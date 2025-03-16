try:
    import collections.abc as collections
except ImportError:
    import collections as collections


def flatten(parameters):
    for e in parameters:
        if isinstance(e, collections.Iterable) and not isinstance(e, str):
            for ee in flatten(e):
                yield ee
        else:
            yield e


def flatten_parameters(parameters):
    return ",".join(map(str, flatten(parameters)))


def flatten_parameters_to_bytestring(parameters):
    return b",".join(map(_misc_to_bytes, flatten(parameters)))


def _misc_to_bytes(m):
    return str(m).encode("utf8")
