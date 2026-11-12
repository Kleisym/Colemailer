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
    private static final Pattern WATERMARK = pattern("(?:отправлено|передано|переслано|опубликовано|рассылка|sent|posted)\\s+(?:через|с\\s+помощью|при\\s+помощи|via|through|by)\\s+@[a-z0-9_]{4,32}\\s*$");
    private static final Pattern TARIFF_HEADER = pattern("\\b(?:репост\\w*|размещени\\w*|рассылк\\w*|закреп\\w*)\\s*:");
    private static final Pattern TARIFF_ROW = pattern("(?m)^[\\p{P}\\p{S}\\p{M} \\t]{0,8}\\d+[ \\t]*(?:минут(?:а|ы)?|час(?:а|ов)?|сут(?:ки|ок)|д(?:ень|ня|ней))[ \\t]*[-–—:=][ \\t]*\\d+(?:[.,]\\d+)?[ \\t]*(?:\\$|₽|€|v|ton|руб\\w*|звезд\\w*)?[\\p{P}\\p{S}\\p{M} \\t]*$");
    private static final Pattern AUTH = pattern("(?:my\\.telegram\\.org|login\\s*code|confirmation\\s*code|код\\s+(?:входа|подтверждения))");
    private static final Pattern RECRUIT = pattern("ищ[уе]\\w*\\s+(?:людей|сотрудник\\w*|работник\\w*)|набор\\s+в\\s+команду");
    private static final Pattern JOB_DETAIL = pattern("профит|график|обучение\\s*:\\s*бесплатно|трафик|под\\s+процент");
    private static final Pattern SMM = pattern("\\b(?:клик(?:и|ов)|накрутк\\w*|залив|просмотр(?:ы|ов))\\b");
    private static final Pattern REFERRAL = pattern("(?:t\\.me|telegram\\.me)/[^\\s]+[?&]startapp=");
    private static final Pattern GIFT = pattern("nft|нфт|подар(?:ок|ки|ков)");
    private static final Pattern GIFT_CTA = pattern("бесплатно|хочешь\\s+улучшить|получить\\s+nft");
    private static final Pattern JOIN_CTA = pattern("\\b(?:присоединяй(?:ся|тесь)|заход(?:и|ите)|вступ(?:ай|айте)|залета(?:й|те))\\b");
    private static final Pattern DESTINATION = pattern("(?:t\\.me|telegram\\.me)/([a-z0-9_+/-]+)");

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
        if (contact && RECRUIT.matcher(text).find()) {
            java.util.regex.Matcher details = JOB_DETAIL.matcher(text);
            int count = 0;
            while (details.find()) if (++count >= 2) return true;
        }
        if (contact && SMM.matcher(text).find() && price && (routing || WATERMARK.matcher(text).find())) return true;
        if (contact && REFERRAL.matcher(text).find() && GIFT.matcher(text).find() && GIFT_CTA.matcher(text).find()) return true;
        if (JOIN_CTA.matcher(text).find()) {
            java.util.HashSet<String> destinations = new java.util.HashSet<>();
            java.util.regex.Matcher links = DESTINATION.matcher(text);
            while (links.find()) if (!destinations.add(links.group(1))) return true;
        }
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
