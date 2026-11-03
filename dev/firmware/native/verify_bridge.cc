extern "C" int c2_exec_pipeline(void *function, void *object) {
    typedef void (*Function)(void *);
    try {
        reinterpret_cast<Function>(function)(object);
        return 0;
    } catch (...) {
        return 1;
    }
}
