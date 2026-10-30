package com.colemailer.app;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.security.MessageDigest;

final class UpdateFileTransfer {
    interface Validator { boolean valid(File file); }

    static File copy(InputStream input, File target, long contentLength, long assetSize,
                     String sha256, Validator validator) throws Exception {
        File temp = File.createTempFile("update-", ".apk", target.getParentFile());
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            try (FileOutputStream output = new FileOutputStream(temp)) {
                byte[] buf = new byte[65536];
                int n;
                while ((n = input.read(buf)) != -1) {
                    output.write(buf, 0, n);
                    digest.update(buf, 0, n);
                }
            }
            long size = temp.length();
            if ((contentLength >= 0 && size != contentLength) || (assetSize > 0 && size != assetSize)) return null;
            if (sha256 != null && !hex(digest.digest()).equalsIgnoreCase(sha256)) return null;
            if (!validator.valid(temp) || !temp.renameTo(target)) return null;
            return target;
        } finally {
            temp.delete();
        }
    }

    private static String hex(byte[] data) {
        StringBuilder result = new StringBuilder(data.length * 2);
        for (byte b : data) result.append(String.format("%02x", b & 0xff));
        return result.toString();
    }
}
