package com.ptc.pfc.pfcModelItem;

import java.nio.file.*;
import java.util.*;

/** One fake part with two user parameters, one text parameter and one dimension. */
public class Model {
    public static final Model INSTANCE = new Model();
    public final Parameters params = new Parameters();
    public final Dimension dim = new Dimension("d1", 10.5);
    public int regenerations = 0;

    public Model() {
        params.add(new Parameter("LENGTH", new ParamValue(60.0, null)));
        params.add(new Parameter("WIDTH", new ParamValue(40.0, null)));
        params.add(new Parameter("NOTE", new ParamValue(null, "hello")));
    }
    public String GetFullName() { return System.getProperty("fake.model", "bracket.prt"); }
    public Parameters ListParams() { return params; }
    public ModelItems ListItems(ModelItemType type) { ModelItems m = new ModelItems(); if (type == ModelItemType.ITEM_DIMENSION) m.add(dim); return m; }
    public void Regenerate(Object instructions) { regenerations++; }
    public MassProperty GetMassProperty(String coordSys) {
        double v = dim.GetDimValue();
        for (Parameter p : params.items) { try { v += p.GetValue().GetDoubleValue(); } catch (Exception e) { } }
        return new MassProperty(v);
    }
    public void Export(String path, Object instructions) throws Exception {
        String src = System.getProperty("fake.step");
        if (src == null) throw new Exception("XToolkitNotFound: fake.step not set");
        Files.copy(Paths.get(src), Paths.get(path), StandardCopyOption.REPLACE_EXISTING);
    }
}
