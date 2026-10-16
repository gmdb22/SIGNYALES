Recorded gesture data goes here, one subfolder per label, e.g.:

    data/
      kumusta/
        rep_0000.npz
        rep_0001.npz
      salamat/
        rep_0000.npz
        ...

Use pi-side/tools/collect_gesture.py to record these.

Folders whose names start with "_" or "." are ignored by training (for
example, rename throwaway sanity recordings to _stage7b_fist). Every other
subfolder becomes a class.
