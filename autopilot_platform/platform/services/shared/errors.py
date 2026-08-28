"""业务已提交后，非关键副作用允许捕获的异常。"""

BEST_EFFORT_ERRS = (
    OSError,
    RuntimeError,
    ValueError,
    TypeError,
    AttributeError,
    ImportError,
    LookupError,
    PermissionError,
)
