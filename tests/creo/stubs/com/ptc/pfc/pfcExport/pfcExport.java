package com.ptc.pfc.pfcExport;

public class pfcExport {
    public static GeometryFlags GeometryFlags_Create() { return new GeometryFlags(); }
    public static Object STEP3DExportInstructions_Create(Object cfg, GeometryFlags flags) {
        if (cfg == null || flags == null) throw new IllegalArgumentException("config and flags are required");
        return new Object();
    }
}
