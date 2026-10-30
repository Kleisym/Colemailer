import shutil
import subprocess
from pathlib import Path

import pytest


def test_update_transfer_checks_and_cleans_partial_downloads(tmp_path):
    javac, java = shutil.which('javac'), shutil.which('java')
    if not javac or not java:
        pytest.skip('JDK required')
    root = Path(__file__).resolve().parents[1]
    source = root / 'android/app/src/main/java/com/colemailer/app/UpdateFileTransfer.java'
    harness = tmp_path / 'TransferTest.java'
    harness.write_text(r'''package com.colemailer.app;
import java.io.*;
import java.nio.file.*;
public class TransferTest {
    static void check(boolean ok) { if (!ok) throw new AssertionError(); }
    public static void main(String[] args) throws Exception {
        File dir = new File(args[0]); File target = new File(dir, "release.apk");
        byte[] data = "abc".getBytes("UTF-8");
        String hash = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";
        InputStream broken = new InputStream() {
            int n = 0;
            public int read() throws IOException { if (n++ == 0) return 97; throw new IOException("interrupted"); }
        };
        try { UpdateFileTransfer.copy(broken, target, 3, 3, hash, f -> true); throw new AssertionError(); }
        catch (IOException expected) { }
        check(!target.exists()); check(dir.list().length == 0);
        check(UpdateFileTransfer.copy(new ByteArrayInputStream(data), target, 4, 3, hash, f -> true) == null);
        check(UpdateFileTransfer.copy(new ByteArrayInputStream(data), target, 3, 4, hash, f -> true) == null);
        check(UpdateFileTransfer.copy(new ByteArrayInputStream(data), target, 3, 3, "wrong", f -> true) == null);
        check(UpdateFileTransfer.copy(new ByteArrayInputStream(data), target, 3, 3, hash, f -> false) == null);
        check(!target.exists()); check(dir.list().length == 0);
        check(UpdateFileTransfer.copy(new ByteArrayInputStream(data), target, 3, 3, hash, f -> true) != null);
        check(java.util.Arrays.equals(Files.readAllBytes(target.toPath()), data));
        check(target.delete());
        check(UpdateFileTransfer.copy(new ByteArrayInputStream(data), target, -1, 0, null, f -> true) != null);
        System.out.println("transfer tests passed");
    }
}''', encoding='utf-8')
    classes = tmp_path / 'classes'
    files = tmp_path / 'files'
    classes.mkdir()
    files.mkdir()
    subprocess.run([javac, '-encoding', 'UTF-8', '-d', str(classes), str(source), str(harness)], check=True, capture_output=True, text=True)
    run = subprocess.run([java, '-cp', str(classes), 'com.colemailer.app.TransferTest', str(files)], check=True, capture_output=True, text=True)
    assert run.stdout.strip() == 'transfer tests passed'
