package com.colemailer.app;

import java.text.Normalizer;
import java.util.HashSet;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Conservative, offline policy for posted group notifications, not a sound interceptor. */
final class AdNotificationFilter {
    private static final int MAX_TEXT = 8192;
    private static final int MAX_MESSAGES = 25;
    private static final Pattern HANDLE = pattern("(?<![\\w@])@[a-z0-9_]{4,32}\\b|https?://[^\\s]+|t\\.me/[^\\s]+");
    private static final Pattern SPACED = pattern("(?<![\\p{L}0-9_])(?:[а-яa-z][.\\-_*•|·~/\\\\]{1,2}){3,}[а-яa-z](?![\\p{L}0-9_])");
    private static final Pattern SPACED_WS = pattern("(?<![\\p{L}0-9_])(?:[а-я] ){3,}[а-я](?![\\p{L}0-9_])");
    private static final Pattern WORD = pattern("[0-9a-zа-я]+");
    private static final Pattern CYR = Pattern.compile("[а-я]");
    private static final Pattern LAT = Pattern.compile("[a-z]");
    private static final Pattern HOMOGLYPH_ONLY = Pattern.compile("^[aeopcxkymthbun]+$");
    private static final Pattern HOMOGLYPH_SPAM = pattern("^(?:ворк\\w*|курс\\w*|прайс\\w*|скуп\\w*|продам|продаю|продаем|куплю|мтс|крипт\\w*|звезд\\w*|акк\\w*|бонус\\w*|казик\\w*|казино|интим\\w*|дроп\\w*|обнал\\w*|выплат\\w*|гарант\\w*)$");
    private static final Pattern SALE = pattern("\\b(?:продаю|продам|продаем|продажа|скупаю|скупка|скупаем|предлагаю|предлагаем|сдам|сдаю|принимаю|принимаем|при[её]м\\s+(?:смс|номер\\w*|физ\\w*|акк\\w*)|выгодн\\w*\\s+(?:тем\\w*|услови\\w*|курс\\w*)|в\\s+продаже|в\\s+наличии)\\b");
    private static final Pattern CATALOG = pattern("\\b(?:прайс\\w*|каталог\\w*|отзывы|price\\s*list)\\b");
    private static final Pattern CONTACT = pattern("\\b(?:писать|пишите|пиши|заказать|купить|обращайтесь|контакты|в\\s+лс|в\\s+личку|в\\s+био)\\b");
    private static final Pattern PRICE = pattern("\\d+(?:[.,]\\d+)?\\s*(?:\\$|₽|€|руб\\w*|usd|ton|тон|звезд\\w*)|\\$\\s*\\d+");
    private static final Pattern WATERMARK = pattern("(?:отправленн?о|передано|переслано|опубликовано|рассылка|разослано|доставлено|запощено|sent|posted)\\s+(?:через|с\\s+помощью|при\\s+помощи|via|through|by)\\s+@[a-z0-9_]{4,32}\\b");
    private static final Pattern TARIFF_HEADER = pattern("\\b(?:репост\\w*|размещени\\w*|рассылк\\w*|закреп\\w*|тариф\\w*)\\s*:");
    private static final Pattern TARIFF_ROW = pattern("(?m)^[\\p{P}\\p{S}\\p{M} \\t]{0,8}\\d+[ \\t]*(?:минут(?:а|ы)?|час(?:а|ов)?|сут(?:ки|ок)|д(?:ень|ня|ней))[ \\t]*[-–—:=][ \\t]*\\d+(?:[.,]\\d+)?[ \\t]*(?:\\$|₽|€|v|ton|руб\\w*|звезд\\w*)?[\\p{P}\\p{S}\\p{M} \\t]*$");
    private static final Pattern AUTH = pattern("(?:my\\.telegram\\.org|login\\s*code|confirmation\\s*code|код\\s+(?:входа|подтверждения))");
    private static final Pattern RECRUIT = pattern("ищ[уе]\\w*\\s+(?:людей|сотрудник\\w*|работник\\w*)|набор\\s+в\\s+команду");
    private static final Pattern JOB_DETAIL = pattern("профит|график|обучение\\s*:\\s*бесплатно|трафик|под\\s+процент");
    private static final Pattern WORK_SIM = pattern("(?:\\b(?:ворк\\w*|заработ\\w*|зарабат\\w*|физ(?:\\s*номер\\w*|\\s*сим\\w*|\\s*акк\\w*|ы|ов)?|е?-?сим\\w*|esim|симк\\w*|сим[-\\s]*карт\\w*|нерег\\w*|при[её]м\\s+смс|момент(?:альн\\w*)?\\s+оплат\\w*|выплат\\w*\\s+(?:сразу|момент\\w*|от)|гарант\\w*|репутац\\w*\\s+в\\s+тим\\w*|тим[аеу]\\s+(?:в\\s+био|у\\s+\\w+\\s+в\\s+био))\\b|(?<![\\w])\\+rep\\b)");
    private static final Pattern CARRIER = pattern("\\b(?:билайн\\w*|мтс|мегафон\\w*|теле2|tele2|йота|yota|сб[-\\s]*моб\\w*|сбермоб\\w*|т[-\\s]*мобайл\\w*|тинькофф\\s*моб\\w*)\\b");
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
        return "org.telegram.messenger".equals(name)
                || "org.telegram.messenger.web".equals(name)
                || "org.telegram.messenger.beta".equals(name)
                || "org.telegram.plus".equals(name)
                || "org.thunderdog.challegram".equals(name)
                || "com.radolyn.ayugram".equals(name)
                || "com.exteragram.messenger".equals(name);
    }

    private static String foldHomoglyphs(String w) {
        StringBuilder sb = new StringBuilder(w.length());
        for (int i = 0; i < w.length(); i++) {
            char c = w.charAt(i);
            switch (c) {
                case 'a': c = 'а'; break;
                case 'e': c = 'е'; break;
                case 'o':
                case '0': c = 'о'; break;
                case 'p': c = 'р'; break;
                case 'c': c = 'с'; break;
                case 'x': c = 'х'; break;
                case 'y': c = 'у'; break;
                case 'k': c = 'к'; break;
                case 'm': c = 'м'; break;
                case 't': c = 'т'; break;
                case 'h': c = 'н'; break;
                case 'b': c = 'в'; break;
                case 'u': c = 'и'; break;
                case 'n': c = 'п'; break;
                case '3': c = 'з'; break;
                case '6': c = 'б'; break;
                default: break;
            }
            sb.append(c);
        }
        return sb.toString();
    }

    private static String normalizeProse(String input) {
        String collapsed = SPACED.matcher(input).replaceAll(m -> m.group().replaceAll("[\\s.\\-_*•|·~/\\\\]", ""));
        collapsed = SPACED_WS.matcher(collapsed).replaceAll(m -> m.group().replace(" ", ""));
        boolean hasCyr = CYR.matcher(collapsed).find();
        Matcher wm = WORD.matcher(collapsed);
        StringBuffer out = new StringBuffer(collapsed.length());
        while (wm.find()) {
            String w = wm.group();
            String rep = w;
            if (CYR.matcher(w).find() && (LAT.matcher(w).find() || w.matches(".*[а-я][036]+[а-я].*"))) {
                rep = foldHomoglyphs(w);
            } else if (hasCyr && w.length() >= 3 && HOMOGLYPH_ONLY.matcher(w).matches()) {
                String cand = foldHomoglyphs(w);
                if (HOMOGLYPH_SPAM.matcher(cand).matches()) rep = cand;
            }
            wm.appendReplacement(out, Matcher.quoteReplacement(rep));
        }
        wm.appendTail(out);
        return out.toString();
    }

    private static int countDistinct(Pattern p, String text) {
        HashSet<String> seen = new HashSet<>();
        Matcher m = p.matcher(text);
        while (m.find()) seen.add(m.group());
        return seen.size();
    }

    static boolean isAd(String raw) {
        if (raw == null || raw.isEmpty() || raw.length() > MAX_TEXT) return false;
        String text = Normalizer.normalize(raw, Normalizer.Form.NFKC).toLowerCase(Locale.ROOT).replace('ё', 'е');
        if (AUTH.matcher(text).find()) return false;
        boolean contact = HANDLE.matcher(text).find();
        String prose = normalizeProse(HANDLE.matcher(text).replaceAll(" "));
        boolean sale = SALE.matcher(prose).find();
        boolean catalogue = CATALOG.matcher(prose).find();
        boolean routing = CONTACT.matcher(prose).find();
        boolean price = PRICE.matcher(prose).find();
        boolean watermark = WATERMARK.matcher(text).find();
        if (contact && RECRUIT.matcher(prose).find()) {
            Matcher details = JOB_DETAIL.matcher(prose);
            int count = 0;
            while (details.find()) if (++count >= 2) return true;
        }
        if (contact && SMM.matcher(prose).find() && price && (routing || watermark)) return true;
        if (contact && REFERRAL.matcher(text).find() && GIFT.matcher(prose).find() && GIFT_CTA.matcher(prose).find()) return true;
        if (JOIN_CTA.matcher(prose).find()) {
            HashSet<String> destinations = new HashSet<>();
            Matcher links = DESTINATION.matcher(text);
            while (links.find()) if (!destinations.add(links.group(1))) return true;
        }
        if (contact && TARIFF_HEADER.matcher(prose).find()) {
            Matcher rows = TARIFF_ROW.matcher(prose);
            int count = 0;
            while (rows.find()) if (++count >= 3) return true;
        }
        int workSim = countDistinct(WORK_SIM, prose);
        int carriers = countDistinct(CARRIER, prose);
        if (contact && ((workSim >= 2 || (workSim >= 1 && carriers >= 2)) && (price || routing || catalogue)
                || (workSim >= 1 && price && routing))) {
            return true;
        }
        return contact && ((sale && (routing || catalogue || price))
                || (catalogue && routing && price)
                || (watermark && (sale || (catalogue && price))));
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
