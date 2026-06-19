const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function timeOfDay(date) {
    let hour = date.getHours();
    const suffix = hour >= 12 ? 'PM' : 'AM';
    hour %= 12;
    if (hour === 0)
        hour = 12;

    return `${hour}:${String(date.getMinutes()).padStart(2, '0')} ${suffix}`;
}

function sameDate(a, b) {
    return a.getFullYear() === b.getFullYear()
        && a.getMonth() === b.getMonth()
        && a.getDate() === b.getDate();
}

function formatExpirationTime(date, now) {
    if (sameDate(date, now))
        return `Resets at ${timeOfDay(date)}`;

    const year = date.getFullYear() === now.getFullYear() ? '' : `, ${date.getFullYear()}`;
    return `Resets at ${MONTHS[date.getMonth()]} ${date.getDate()}${year}, ${timeOfDay(date)}`;
}

function formatCountdown(date, now) {
    const seconds = Math.floor((date - now) / 1000);
    if (seconds <= 0)
        return 'Resets now';
    if (seconds < 60)
        return 'Resets soon';

    const totalMinutes = Math.floor(seconds / 60);
    const minutes = totalMinutes % 60;
    const totalHours = Math.floor(totalMinutes / 60);
    if (totalHours <= 0)
        return `Resets in ${minutes}m`;

    const hours = totalHours % 24;
    const days = Math.floor(totalHours / 24);
    if (days > 0)
        return `Resets in ${days}d ${hours}h ${minutes}m`;

    return `Resets in ${hours}h ${minutes}m`;
}

export function formatResetTime(resetsAt, mode = 'countdown', now = new Date()) {
    const date = resetsAt instanceof Date ? resetsAt : new Date(resetsAt);
    if (Number.isNaN(date.getTime()))
        return '';

    return mode === 'time' ? formatExpirationTime(date, now) : formatCountdown(date, now);
}
