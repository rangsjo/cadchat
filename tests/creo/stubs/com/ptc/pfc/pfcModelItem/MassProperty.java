package com.ptc.pfc.pfcModelItem;

public class MassProperty {
    private final double v;
    public MassProperty(double v) { this.v = v; }
    public double GetVolume() { return v; }
    public double GetSurfaceArea() { return v * 2; }
}
