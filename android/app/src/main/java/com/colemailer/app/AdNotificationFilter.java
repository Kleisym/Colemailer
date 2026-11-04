package com.colemailer.app;

import java.text.Normalizer;
import java.util.Locale;
import java.util.regex.Pattern;

/** Conservative, offline policy for posted group notifications, not a sound interceptor. */
final class AdNotificationFilter {
    private static final int MAX_TEXT = 8192;
    private static final int MAX_MESSAGES = 25;
    private static final Pattern HANDLE = pattern("(?<![\\w@])@[a-z0-9_]{4,32}\\b|https?://[^\\s]+|t\\.me/[^\\s]+");
    private static final Pattern SALE = pattern("\\b(?:продаю|продам|продаем|продажа|скупаю|скупка|предлагаю|в\\s+продаже|в\\s+наличии)\\b");
    private static final Pattern CATALOG = pattern("\\b(?:прайс\\w*|каталог\\w*|отзывы|price\\s*list)\\b");
    private static final Pattern CONTACT = pattern("\\b(?:писать|пишите|пиши|заказать|купить|обращайтесь|контакты|в\\s+лс|в\\s+личку)\\b");
    private static final Pattern PRICE = pattern("\\d+(?:[.,]\\d+)?\\s*(?:\\$|₽|€|руб\\w*|usd|ton|звезд\\w*)|\\$\\s*\\d+");
    private static final Pattern WATERMARK = pattern("(?:отправлено|передано|переслано|опубликовано|sent|posted)\\s+(?:через|с\\s+помощью|при\\s+помощи|via|through|by)\\s+@[a-z0-9_]{4,32}\\s*$");
    private static final Pattern TARIFF_HEADER = pattern("\\b(?:репост\\w*|размещени\\w*|рассылк\\w*|закреп\\w*)\\s*:");
    private static final Pattern TARIFF_ROW = pattern("(?m)^[\\p{P}\\p{S}\\p{M} \\t]{0,8}\\d+[ \\t]*(?:минут(?:а|ы)?|час(?:а|ов)?|сут(?:ки|ок)|д(?:ень|ня|ней))[ \\t]*[-–—:=][ \\t]*\\d+(?:[.,]\\d+)?[ \\t]*(?:\\$|₽|€|v|ton|руб\\w*|звезд\\w*)?[\\p{P}\\p{S}\\p{M} \\t]*$");
    private static final Pattern AUTH = pattern("(?:my\\.telegram\\.org|login\\s*code|confirmation\\s*code|код\\s+(?:входа|подтверждения))");

    private static Pattern pattern(String expression) {
        return Pattern.compile(expression, Pattern.CASE_INSENSITIVE | Pattern.UNICODE_CASE | Pattern.UNICODE_CHARACTER_CLASS);
    }

    static boolean supportsPackage(String name) {
        return "org.telegram.messenger".equals(name) || "org.telegram.messenger.web".equals(name);
    }

    static boolean isAd(String raw) {
        if (raw == null || raw.isEmpty() || raw.length() > MAX_TEXT) return false;
        String text = Normalizer.normalize(raw, Normalizer.Form.NFKC).toLowerCase(Locale.ROOT).replace('ё', 'е');
        if (AUTH.matcher(text).find()) return false;
        boolean contact = HANDLE.matcher(text).find();
        boolean sale = SALE.matcher(text).find();
        boolean catalogue = CATALOG.matcher(text).find();
        boolean routing = CONTACT.matcher(text).find();
        boolean price = PRICE.matcher(text).find();
        if (contact && TARIFF_HEADER.matcher(text).find()) {
            java.util.regex.Matcher rows = TARIFF_ROW.matcher(text);
            int count = 0;
            while (rows.find()) if (++count >= 3) return true;
        }
        return contact && ((sale && (routing || catalogue || price))
                || (catalogue && routing && price)
                || (WATERMARK.matcher(text).find() && (sale || (catalogue && price))));
    }

    static boolean shouldDismiss(String packageName, boolean enabled, boolean summary,
                                 boolean ongoing, boolean group, String[] messages) {
        if (!enabled || !supportsPackage(packageName) || summary || ongoing || !group
                || messages == null || messages.length == 0 || messages.length > MAX_MESSAGES) return false;
        // Cancelling a notification removes the entire bundle: keep it if even
        // one message is ordinary, hidden, or unrecognised.
        for (String message : messages) if (!isAd(message)) return false;
        return true;
    }
}
