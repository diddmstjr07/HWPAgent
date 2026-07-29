        document.querySelectorAll('[data-social-auth]').forEach(link => {
            const base = link.getAttribute('href') || '';
            link.setAttribute('href', withNextParam(base));
        });

