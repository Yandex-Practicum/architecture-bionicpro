package bionicpro;

import org.keycloak.broker.oidc.OAuth2IdentityProviderConfig;
import org.keycloak.broker.provider.AbstractIdentityProviderFactory;
import org.keycloak.broker.social.SocialIdentityProviderFactory;
import org.keycloak.models.IdentityProviderModel;
import org.keycloak.models.KeycloakSession;

public class YandexIdentityProviderFactory extends AbstractIdentityProviderFactory<YandexIdentityProvider>
        implements SocialIdentityProviderFactory<YandexIdentityProvider> {
    @Override public String getName() { return "Yandex ID"; }
    @Override public String getId() { return "yandex"; }
    @Override public YandexIdentityProvider create(KeycloakSession session, IdentityProviderModel model) {
        return new YandexIdentityProvider(session, new OAuth2IdentityProviderConfig(model));
    }
    @Override public OAuth2IdentityProviderConfig createConfig() { return new OAuth2IdentityProviderConfig(); }
}
