import java.io.*;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

/**
 * cadchat <-> Creo Parametric bridge (J-Link asynchronous mode, "Object TOOLKIT Java Free").
 *
 * Speaks JSON lines on stdin/stdout so the Python side (tools/creolink.py) stays testable without Creo:
 *   {"id":1,"cmd":"connect"}            attach to the running Creo (or {"start":"<command line>"} to launch one)
 *   {"id":2,"cmd":"status"}             connected, current model, geometry fingerprint
 *   {"id":3,"cmd":"params"}             user parameters and dimensions of the current model
 *   {"id":4,"cmd":"set","name":"d1","value":12.5}
 *   {"id":5,"cmd":"regenerate"}
 *   {"id":6,"cmd":"export_step","path":"C:\\\\x\\\\part.stp"}
 *   {"id":7,"cmd":"quit"}
 *
 * All Creo calls go through reflection by method name, so this file compiles without Creo's jars and a wrong class or
 * method name shows up as a readable error for that one command instead of breaking the build. Run it with
 *   java -cp <creo>\Common Files\text\java\pfcasync.jar CreoBridge.java
 * and PATH containing the folder with pfcasyncmt.dll and PRO_COMM_MSG_EXE set (tools/creolink.py does all of this).
 */
public class CreoBridge {
    static Object conn, session;

    // ------------------------------------------------------------------ reflection helpers
    static Object coerce(Class<?> t, Object a) {
        if (a == null) return null;
        if (a instanceof Number n) {
            if (t == double.class || t == Double.class) return n.doubleValue();
            if (t == int.class || t == Integer.class) return n.intValue();
            if (t == long.class || t == Long.class) return n.longValue();
        }
        return a;
    }

    static Exception unwrap(InvocationTargetException e) {
        Throwable t = e.getCause() != null ? e.getCause() : e;
        String msg = t.getMessage();
        return new Exception(t.getClass().getSimpleName() + (msg != null && !msg.isEmpty() ? ": " + msg : ""));
    }

    static Object invoke(Class<?> cls, Object target, String name, Object... args) throws Exception {
        Exception last = null;
        for (Method m : cls.getMethods()) {
            if (!m.getName().equals(name) || m.getParameterCount() != args.length) continue;
            Class<?>[] pt = m.getParameterTypes();
            Object[] a = new Object[args.length];
            for (int i = 0; i < a.length; i++) a[i] = coerce(pt[i], args[i]);
            try {
                return m.invoke(target, a);
            } catch (InvocationTargetException e) {
                last = unwrap(e);
            } catch (IllegalArgumentException e) {
                last = new Exception("bad argument for " + cls.getSimpleName() + "." + name + ": " + e.getMessage());
            }
        }
        if (last != null) throw last;
        throw new NoSuchMethodException(cls.getName() + "." + name + " with " + args.length + " argument(s)");
    }

    static Object call(Object target, String name, Object... args) throws Exception {
        return invoke(target.getClass(), target, name, args);
    }

    static Object callStatic(String cls, String name, Object... args) throws Exception {
        return invoke(Class.forName(cls), null, name, args);
    }

    static Object field(String[] classNames, String field) throws Exception {
        Exception last = null;
        for (String c : classNames) {
            try {
                return Class.forName(c).getField(field).get(null);
            } catch (Exception e) {
                last = e;
            }
        }
        throw new Exception("cannot find " + field + " in " + String.join(" or ", classNames) + " (" + last + ")");
    }

    static int size(Object seq) throws Exception { return ((Number) call(seq, "getarraysize")).intValue(); }

    // ------------------------------------------------------------------ Creo operations
    static void connect(String start) throws Exception {
        if (!Boolean.getBoolean("creo.skipLoadLibrary")) System.loadLibrary("pfcasyncmt");
        String cls = "com.ptc.pfc.pfcAsyncConnection.pfcAsyncConnection";
        conn = start == null ? callStatic(cls, "AsyncConnection_Connect", null, null, null, null)
                             : callStatic(cls, "AsyncConnection_Start", start, null);
        try {
            session = call(conn, "GetSession");
        } catch (NoSuchMethodException e) {
            session = call(conn, "GetCurrentSession");
        }
    }

    static Object requireModel() throws Exception {
        if (session == null) throw new Exception("not connected to Creo (send connect first)");
        Object m = call(session, "GetCurrentModel");
        if (m == null) throw new Exception("no model is open in Creo");
        return m;
    }

    static String fingerprint(Object model) {
        try {
            Object mp = call(model, "GetMassProperty", (Object) null);
            return String.format(Locale.ROOT, "%.6f|%.6f", ((Number) call(mp, "GetVolume")).doubleValue(), ((Number) call(mp, "GetSurfaceArea")).doubleValue());
        } catch (Exception e) {
            return "";                                  // assemblies without mass properties: the Python side falls back to manual sync
        }
    }

    static Object readValue(Object paramValue, Map<String, Object> out) {
        String[][] tries = {{"GetDoubleValue", "double"}, {"GetIntValue", "int"}, {"GetStringValue", "string"}, {"GetBoolValue", "bool"}};
        for (String[] t : tries) {
            try {
                Object v = call(paramValue, t[0]);
                out.put("type", t[1]);
                return v;
            } catch (Exception e) { /* wrong type, try the next one */ }
        }
        out.put("type", "unknown");
        return null;
    }

    static Object dimensionType() throws Exception {
        return field(new String[]{"com.ptc.pfc.pfcModelItem.ModelItemType", "com.ptc.pfc.pfcModel.ModelItemType"}, "ITEM_DIMENSION");
    }

    static List<Object> userParams(Object model) throws Exception {
        List<Object> out = new ArrayList<>();
        Object ps = call(model, "ListParams");
        for (int i = 0; i < size(ps); i++) out.add(call(ps, "get", i));
        return out;
    }

    static List<Object> dimensions(Object model) throws Exception {
        List<Object> out = new ArrayList<>();
        Object items = call(model, "ListItems", dimensionType());
        for (int i = 0; i < size(items); i++) out.add(call(items, "get", i));
        return out;
    }

    static List<Map<String, Object>> params(Object model) throws Exception {
        List<Map<String, Object>> out = new ArrayList<>();
        for (Object p : userParams(model)) {
            Map<String, Object> e = new LinkedHashMap<>();
            e.put("name", call(p, "GetName"));
            e.put("kind", "param");
            e.put("value", readValue(call(p, "GetValue"), e));
            out.add(e);
        }
        try {
            for (Object d : dimensions(model)) {
                Map<String, Object> e = new LinkedHashMap<>();
                e.put("name", call(d, "GetSymbol"));
                e.put("kind", "dimension");
                e.put("value", call(d, "GetDimValue"));
                e.put("type", "double");
                out.add(e);
            }
        } catch (Exception ex) {
            Map<String, Object> e = new LinkedHashMap<>();
            e.put("name", "(dimensions unavailable)");
            e.put("kind", "note");
            e.put("value", ex.getMessage());
            e.put("type", "string");
            out.add(e);
        }
        return out;
    }

    static void set(Object model, String name, Object value) throws Exception {
        for (Object p : userParams(model)) {
            if (!name.equals(call(p, "GetName"))) continue;
            Object pv = call(p, "GetValue");
            if (value instanceof Number n) {
                Map<String, Object> t = new HashMap<>();
                readValue(pv, t);
                if ("int".equals(t.get("type"))) call(pv, "SetIntValue", n.intValue());
                else call(pv, "SetDoubleValue", n.doubleValue());
            } else if (value instanceof Boolean b) {
                call(pv, "SetBoolValue", b);
            } else {
                call(pv, "SetStringValue", String.valueOf(value));
            }
            call(p, "SetValue", pv);
            return;
        }
        for (Object d : dimensions(model)) {
            if (name.equals(call(d, "GetSymbol"))) {
                if (!(value instanceof Number)) throw new Exception("dimension " + name + " needs a number");
                call(d, "SetDimValue", ((Number) value).doubleValue());
                return;
            }
        }
        throw new Exception("no parameter or dimension named " + name);
    }

    static void exportStep(Object model, String path) throws Exception {
        String pkg = "com.ptc.pfc.pfcExport.";
        Object flags = callStatic(pkg + "pfcExport", "GeometryFlags_Create");
        for (String[] f : new String[][]{{"SetAsSolids", "true"}, {"SetAsSurfaces", "false"}, {"SetAsQuilts", "false"}, {"SetAsWireframe", "false"}}) {
            try { call(flags, f[0], Boolean.parseBoolean(f[1])); } catch (Exception e) { /* option not present in this release */ }
        }
        Object cfg = field(new String[]{pkg + "AssemblyConfiguration"}, "EXPORT_ASM_SINGLE_FILE");
        Object instr = callStatic(pkg + "pfcExport", "STEP3DExportInstructions_Create", cfg, flags);
        call(model, "Export", path, instr);
    }

    static Map<String, Object> handle(String cmd, Map<String, Object> req) throws Exception {
        Map<String, Object> r = new LinkedHashMap<>();
        switch (cmd) {
            case "ping" -> { }
            case "connect" -> connect((String) req.get("start"));
            case "status" -> {
                r.put("connected", session != null);
                if (session != null) {
                    Object m = call(session, "GetCurrentModel");
                    r.put("model", m == null ? null : call(m, "GetFullName"));
                    r.put("fingerprint", m == null ? "" : fingerprint(m));
                }
            }
            case "params" -> r.put("params", params(requireModel()));
            case "set" -> set(requireModel(), (String) req.get("name"), req.get("value"));
            case "regenerate" -> call(requireModel(), "Regenerate", (Object) null);
            case "export_step" -> exportStep(requireModel(), (String) req.get("path"));
            case "disconnect" -> {
                if (conn != null) call(conn, "Disconnect", (Object) null);
                conn = session = null;
            }
            default -> throw new Exception("unknown command: " + cmd);
        }
        return r;
    }

    // ------------------------------------------------------------------ JSON lines (flat objects only)
    static Map<String, Object> parse(String s) {
        Map<String, Object> m = new LinkedHashMap<>();
        int[] i = {0};
        skip(s, i);
        expect(s, i, '{');
        skip(s, i);
        if (s.charAt(i[0]) == '}') return m;
        while (true) {
            skip(s, i);
            String k = str(s, i);
            skip(s, i);
            expect(s, i, ':');
            skip(s, i);
            m.put(k, val(s, i));
            skip(s, i);
            if (s.charAt(i[0]) == ',') { i[0]++; continue; }
            expect(s, i, '}');
            return m;
        }
    }

    static void skip(String s, int[] i) { while (i[0] < s.length() && Character.isWhitespace(s.charAt(i[0]))) i[0]++; }

    static void expect(String s, int[] i, char c) {
        if (i[0] >= s.length() || s.charAt(i[0]) != c) throw new IllegalArgumentException("bad JSON, expected '" + c + "' at " + i[0]);
        i[0]++;
    }

    static String str(String s, int[] i) {
        expect(s, i, '"');
        StringBuilder b = new StringBuilder();
        while (s.charAt(i[0]) != '"') {
            char c = s.charAt(i[0]++);
            if (c == '\\') {
                char e = s.charAt(i[0]++);
                switch (e) {
                    case 'n' -> b.append('\n');
                    case 't' -> b.append('\t');
                    case 'r' -> b.append('\r');
                    case 'u' -> { b.append((char) Integer.parseInt(s.substring(i[0], i[0] + 4), 16)); i[0] += 4; }
                    default -> b.append(e);
                }
            } else b.append(c);
        }
        i[0]++;
        return b.toString();
    }

    static Object val(String s, int[] i) {
        char c = s.charAt(i[0]);
        if (c == '"') return str(s, i);
        if (s.startsWith("true", i[0])) { i[0] += 4; return true; }
        if (s.startsWith("false", i[0])) { i[0] += 5; return false; }
        if (s.startsWith("null", i[0])) { i[0] += 4; return null; }
        int st = i[0];
        while (i[0] < s.length() && "+-0123456789.eE".indexOf(s.charAt(i[0])) >= 0) i[0]++;
        if (st == i[0]) throw new IllegalArgumentException("bad JSON value at " + st);
        return Double.parseDouble(s.substring(st, i[0]));
    }

    static void write(StringBuilder b, Object v) {
        if (v == null) b.append("null");
        else if (v instanceof Boolean) b.append(v);
        else if (v instanceof Number n) b.append(n.doubleValue() == Math.rint(n.doubleValue()) && Math.abs(n.doubleValue()) < 1e15 ? String.valueOf(n.longValue()) : String.valueOf(n.doubleValue()));
        else if (v instanceof Map<?, ?> m) {
            b.append('{');
            boolean first = true;
            for (Map.Entry<?, ?> e : m.entrySet()) {
                if (!first) b.append(',');
                first = false;
                write(b, String.valueOf(e.getKey()));
                b.append(':');
                write(b, e.getValue());
            }
            b.append('}');
        } else if (v instanceof List<?> l) {
            b.append('[');
            for (int k = 0; k < l.size(); k++) { if (k > 0) b.append(','); write(b, l.get(k)); }
            b.append(']');
        } else {
            b.append('"');
            for (char c : v.toString().toCharArray()) {
                switch (c) {
                    case '"' -> b.append("\\\"");
                    case '\\' -> b.append("\\\\");
                    case '\n' -> b.append("\\n");
                    case '\r' -> b.append("\\r");
                    case '\t' -> b.append("\\t");
                    default -> { if (c < 0x20) b.append(String.format("\\u%04x", (int) c)); else b.append(c); }
                }
            }
            b.append('"');
        }
    }

    public static void main(String[] args) throws Exception {
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        PrintStream out = new PrintStream(new FileOutputStream(FileDescriptor.out), true, StandardCharsets.UTF_8);
        System.setOut(System.err);                      // stray prints from the Creo library must not corrupt the protocol channel
        String line;
        while ((line = in.readLine()) != null) {
            if (line.isBlank()) continue;
            Map<String, Object> reply = new LinkedHashMap<>();
            Object id = null;
            try {
                Map<String, Object> req = parse(line);
                id = req.get("id");
                String cmd = String.valueOf(req.get("cmd"));
                if (cmd.equals("quit")) {
                    reply.put("id", id);
                    reply.put("ok", true);
                    StringBuilder b = new StringBuilder();
                    write(b, reply);
                    out.println(b);
                    return;
                }
                Map<String, Object> result = handle(cmd, req);
                reply.put("id", id);
                reply.put("ok", true);
                reply.putAll(result);
            } catch (Throwable t) {
                reply.clear();
                reply.put("id", id);
                reply.put("ok", false);
                reply.put("error", t.getMessage() != null ? t.getMessage() : t.getClass().getSimpleName());
            }
            StringBuilder b = new StringBuilder();
            write(b, reply);
            out.println(b);
        }
    }
}
